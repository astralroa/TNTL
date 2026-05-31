import json
import random
import urllib.request
import urllib.error
from datetime import datetime
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone


# In-memory game state per room (keyed by room_code)
# Structure:
# ROOM_STATE[code] = {
#   'players': {player_id: {name, face_index, laugh_count, bomb_charges, consecutive_survived}},
#   'mode': 'hotseat' | 'first_laugh',
#   'phase': 'lobby' | 'calibration' | 'playing' | 'truth_dare' | 'ended',
#   'hot_seat_index': int,  # index into player_order list
#   'player_order': [player_id, ...],
#   'round_number': int,
#   'current_prompt': {text, kind},
#   'bomb_queue': [],
#   'bomb_active': False,
#   'truth_history': set(),
#   'dare_history': set(),
#   'channel_map': {player_id: channel_name},
#   'room_db_id': int,
#   'current_round_db_id': int,
# }
ROOM_STATE = {}

BOMB_ASSETS = {
    'gif': [
        {'id': 'laugh1', 'url': 'https://media.giphy.com/media/3o7TKqnN349PBTHyg8/giphy.gif', 'label': 'Crying Laugh'},
        {'id': 'laugh2', 'url': 'https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif', 'label': 'Wheeze'},
        {'id': 'laugh3', 'url': 'https://media.giphy.com/media/GeimqsH0TLDt4tScGw/giphy.gif', 'label': 'Clown'},
        {'id': 'laugh4', 'url': 'https://media.giphy.com/media/5GoVLqeAOo6PK/giphy.gif', 'label': 'Funny Cat'},
        {'id': 'laugh5', 'url': 'https://media.giphy.com/media/Vuw9m5wXviFIQ/giphy.gif', 'label': 'Ha'},
    ],
    'sound': [
        {'id': 'airhorn', 'label': 'Air Horn', 'url': '/static/game/sounds/airhorn.mp3'},
        {'id': 'laugh_track', 'label': 'Laugh Track', 'url': '/static/game/sounds/laugh_track.mp3'},
        {'id': 'sad_trombone', 'label': 'Sad Trombone', 'url': '/static/game/sounds/sad_trombone.mp3'},
    ]
}


def fetch_prompt(kind: str) -> str | None:
    url = f"https://api.truthordarebot.xyz/v1/{kind}?rating=r"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            return data.get("question")
    except Exception:
        return None


@database_sync_to_async
def get_room_from_db(code):
    from .models import Room
    try:
        return Room.objects.get(code=code, is_active=True)
    except Room.DoesNotExist:
        return None


@database_sync_to_async
def get_custom_prompts(room_id, kind):
    from .models import CustomPrompt
    return list(CustomPrompt.objects.filter(room_id=room_id, kind=kind).values_list('text', flat=True))


@database_sync_to_async
def create_game_round(room_id, round_number, player_id):
    from .models import GameRound
    r = GameRound.objects.create(
        room_id=room_id,
        round_number=round_number,
        hot_seat_player_id=player_id,
    )
    return r.id


@database_sync_to_async
def complete_round(round_id, prompt_text, prompt_type, laughed):
    from .models import GameRound
    try:
        r = GameRound.objects.get(id=round_id)
        r.prompt_text = prompt_text
        r.prompt_type = prompt_type
        r.completed = True
        if laughed:
            r.laugh_detected_at = timezone.now()
        r.save()
    except Exception:
        pass


@database_sync_to_async
def update_player_stats(player_id, laugh_count, bomb_charges, consecutive_survived):
    from .models import Player
    try:
        Player.objects.filter(id=player_id).update(
            laugh_count=laugh_count,
            bomb_charges=bomb_charges,
            consecutive_survived=consecutive_survived,
        )
    except Exception:
        pass


@database_sync_to_async
def save_bomb_record(room_id, owner_id, bomb_type, asset_id, round_id):
    from .models import LaughBomb
    LaughBomb.objects.create(
        room_id=room_id,
        owner_id=owner_id,
        bomb_type=bomb_type,
        asset_id=asset_id,
        fired_at_round_id=round_id,
    )


class GameConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code']
        self.group_name = f'room_{self.room_code}'
        self.player_id = None

        room = await get_room_from_db(self.room_code)
        if not room:
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Init room state if needed
        if self.room_code not in ROOM_STATE:
            ROOM_STATE[self.room_code] = {
                'players': {},
                'mode': room.mode,
                'content_mode': room.content_mode,
                'phase': 'lobby',
                'hot_seat_index': 0,
                'player_order': [],
                'round_number': 0,
                'current_prompt': None,
                'bomb_queue': [],
                'bomb_active': False,
                'truth_history': set(),
                'dare_history': set(),
                'channel_map': {},
                'room_db_id': room.id,
                'current_round_db_id': None,
            }

    async def disconnect(self, close_code):
        state = ROOM_STATE.get(self.room_code)
        if state and self.player_id:
            if self.player_id in state['channel_map']:
                del state['channel_map'][self.player_id]
            if self.player_id in state['players']:
                state['players'][self.player_id]['connected'] = False
            await self.broadcast('player_left', {
                'player_id': self.player_id,
                'players': self.serialize_players(state),
            })
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            return
        event = data.get('type')
        if event == 'join':
            await self.handle_join(data)
        elif event == 'start_game':
            await self.handle_start_game(data)
        elif event == 'calibration_done':
            await self.handle_calibration_done(data)
        elif event == 'laugh_detected':
            await self.handle_laugh_detected(data)
        elif event == 'choose_prompt':
            await self.handle_choose_prompt(data)
        elif event == 'prompt_done':
            await self.handle_prompt_done(data)
        elif event == 'bomb_fire':
            await self.handle_bomb_fire(data)
        elif event == 'bomb_resolved':
            await self.handle_bomb_resolved()
        elif event == 'upload_clip':
            await self.handle_upload_clip(data)
        elif event == 'add_custom_prompt':
            await self.handle_add_custom_prompt(data)
        elif event == 'request_state':
            await self.send_state()

    # ------------------------------------------------------------------ #
    # JOIN
    # ------------------------------------------------------------------ #
    async def handle_join(self, data):
        state = ROOM_STATE[self.room_code]
        if state['phase'] != 'lobby':
            await self.send_error('Game already in progress')
            return

        name = data.get('name', '').strip()[:50]
        face_index = data.get('face_index', 0)  # 0 or 1
        if not name:
            await self.send_error('Name required')
            return
        max_players = 1 if state['mode'] == 'solo' else 2
        if len(state['players']) >= max_players:
            await self.send_error('Room is full — max ' + str(max_players) + ' player(s)')
            return

        # Create player record in DB
        player_id = await self.create_player_db(state['room_db_id'], name, face_index)
        self.player_id = player_id

        state['players'][player_id] = {
            'id': player_id,
            'name': name,
            'face_index': face_index,
            'laugh_count': 0,
            'bomb_charges': 0,
            'consecutive_survived': 0,
            'calibrated': False,
            'connected': True,
        }
        state['channel_map'][player_id] = self.channel_name

        await self.send(text_data=json.dumps({
            'type': 'joined',
            'player_id': player_id,
            'room_code': self.room_code,
            'mode': state['mode'],
        }))

        await self.broadcast('player_joined', {
            'players': self.serialize_players(state),
        })

    # ------------------------------------------------------------------ #
    # START GAME → trigger calibration
    # ------------------------------------------------------------------ #
    async def handle_start_game(self, data):
        state = ROOM_STATE[self.room_code]
        if len(state['players']) < 1:
            await self.send_error('Need at least 1 player')
            return
        if state['phase'] != 'lobby':
            return

        state['phase'] = 'calibration'
        state['player_order'] = list(state['players'].keys())
        random.shuffle(state['player_order'])

        await self.broadcast('calibration_start', {
            'duration': 10,
            'message': 'Look neutral at the camera for 10 seconds...',
            'players': self.serialize_players(state),
        })

    # ------------------------------------------------------------------ #
    # CALIBRATION DONE — client sends baseline expression data
    # ------------------------------------------------------------------ #
    async def handle_calibration_done(self, data):
        state = ROOM_STATE[self.room_code]
        # Client sends all_player_ids for local multi-player (same tab = same WS)
        player_ids = data.get('all_player_ids', [])
        if not player_ids and self.player_id:
            player_ids = [self.player_id]

        for pid in player_ids:
            if pid in state['players']:
                state['players'][pid]['calibrated'] = True
                state['players'][pid]['threshold'] = data.get('threshold', 0.25)

        all_calibrated = all(
            p.get('calibrated', False)
            for p in state['players'].values()
        )

        if all_calibrated and state['phase'] == 'calibration':
            state['phase'] = 'playing'
            await self.start_next_round()

    # ------------------------------------------------------------------ #
    # LAUGH DETECTED
    # ------------------------------------------------------------------ #
    async def handle_laugh_detected(self, data):
        state = ROOM_STATE[self.room_code]
        if state['phase'] != 'playing':
            return

        laughing_face = data.get('face_index', 0)
        laughing_player = self.get_player_by_face(state, laughing_face)
        if not laughing_player:
            return

        mode = state['mode']

        if mode == 'solo':
            # Only one player, any face triggers
            player_id = state['player_order'][0]
            await self.trigger_truth_or_dare(state, player_id)

        elif mode == 'hotseat':
            # Only care about the current hot seat player's face
            hot_seat_id = state['player_order'][state['hot_seat_index']]
            hot_seat = state['players'][hot_seat_id]
            if hot_seat['face_index'] != laughing_face:
                return
            await self.trigger_truth_or_dare(state, hot_seat_id)

        elif mode == 'first_laugh':
            # First face to laugh triggers that player's round
            await self.trigger_truth_or_dare(state, laughing_player['id'])

    # ------------------------------------------------------------------ #
    # CHOOSE PROMPT (truth or dare chosen by player)
    # ------------------------------------------------------------------ #
    async def handle_choose_prompt(self, data):
        state = ROOM_STATE[self.room_code]
        if state['phase'] != 'truth_dare':
            return

        kind = data.get('kind')  # 'truth' or 'dare'
        if kind not in ('truth', 'dare'):
            return

        prompt = await self.get_prompt(state, kind)
        state['current_prompt'] = {'text': prompt, 'kind': kind}

        await self.broadcast('prompt_assigned', {
            'kind': kind,
            'text': prompt,
            'player_id': state.get('laughed_player_id'),
        })

    # ------------------------------------------------------------------ #
    # PROMPT DONE — player completed truth/dare, advance round
    # ------------------------------------------------------------------ #
    async def handle_prompt_done(self, data):
        state = ROOM_STATE[self.room_code]
        if state['phase'] not in ('truth_dare', 'playing'):
            return

        # Complete DB round record if we have one
        if state['current_round_db_id']:
            prompt = state.get('current_prompt') or {}
            await complete_round(
                state['current_round_db_id'],
                prompt.get('text', ''),
                prompt.get('kind', ''),
                laughed=True,
            )

        # Increment laugh count — always, unconditionally
        lp_id = state.get('laughed_player_id')
        if lp_id and lp_id in state['players']:
            p = state['players'][lp_id]
            p['laugh_count'] += 1
            p['consecutive_survived'] = 0
            await update_player_stats(lp_id, p['laugh_count'], p['bomb_charges'], p['consecutive_survived'])
            # Broadcast updated scores immediately so HUD updates
            await self.broadcast('scores_update', {'players': self.serialize_players(state)})

        await self.advance_round(state)

    # ------------------------------------------------------------------ #
    # BOMB FIRE
    # ------------------------------------------------------------------ #
    async def handle_bomb_fire(self, data):
        state = ROOM_STATE[self.room_code]
        if state['phase'] != 'playing':
            return
        if not self.player_id or self.player_id not in state['players']:
            return

        player = state['players'][self.player_id]
        if player['bomb_charges'] < 1:
            return

        bomb_type = data.get('bomb_type')
        if bomb_type not in ('gif', 'sound'):
            return

        assets = BOMB_ASSETS.get(bomb_type, [])
        if not assets:
            return

        asset = random.choice(assets)

        bomb = {
            'attacker_id': self.player_id,
            'attacker_name': player['name'],
            'bomb_type': bomb_type,
            'asset': asset,
        }

        if state['bomb_active']:
            state['bomb_queue'].append(bomb)
            await self.send(text_data=json.dumps({'type': 'bomb_queued'}))
            return

        await self.fire_bomb(state, bomb, player)

    async def fire_bomb(self, state, bomb, player):
        state['bomb_active'] = True
        player['bomb_charges'] -= 1

        await update_player_stats(
            bomb['attacker_id'],
            player['laugh_count'],
            player['bomb_charges'],
            player['consecutive_survived'],
        )

        await save_bomb_record(
            state['room_db_id'],
            bomb['attacker_id'],
            bomb['bomb_type'],
            bomb['asset']['id'],
            state['current_round_db_id'],
        )

        await self.broadcast('bomb_charged', {'players': self.serialize_players(state)})

        # Find hot seat player channel to target
        hot_seat_id = state['player_order'][state['hot_seat_index']] if state['player_order'] else None

        await self.broadcast('bomb_incoming', {
            'attacker_name': bomb['attacker_name'],
            'bomb_type': bomb['bomb_type'],
            'asset': bomb['asset'],
            'target_player_id': hot_seat_id,
        })

    async def handle_bomb_resolved(self):
        state = ROOM_STATE[self.room_code]
        state['bomb_active'] = False

        await self.broadcast('bomb_resolved', {})

        # Fire next queued bomb if any
        if state['bomb_queue']:
            next_bomb = state['bomb_queue'].pop(0)
            next_player = state['players'].get(next_bomb['attacker_id'])
            if next_player and next_player['bomb_charges'] > 0:
                await self.fire_bomb(state, next_bomb, next_player)

    # ------------------------------------------------------------------ #
    # UPLOAD CLIP
    # ------------------------------------------------------------------ #
    async def handle_upload_clip(self, data):
        # Clip upload handled via REST endpoint; this just acks
        await self.send(text_data=json.dumps({'type': 'clip_ack'}))

    # ------------------------------------------------------------------ #
    # ADD CUSTOM PROMPT
    # ------------------------------------------------------------------ #
    async def handle_add_custom_prompt(self, data):
        state = ROOM_STATE[self.room_code]
        kind = data.get('kind')
        text = data.get('text', '').strip()
        if kind not in ('truth', 'dare') or not text:
            return
        await self.save_custom_prompt(state['room_db_id'], kind, text)
        await self.send(text_data=json.dumps({'type': 'custom_prompt_saved', 'kind': kind}))

    # ------------------------------------------------------------------ #
    # INTERNAL HELPERS
    # ------------------------------------------------------------------ #
    async def trigger_truth_or_dare(self, state, player_id):
        if state['phase'] != 'playing':
            return  # already triggered this round, ignore
        state['phase'] = 'truth_dare'
        state['laughed_player_id'] = player_id
        player = state['players'][player_id]
        # Don't increment laugh_count here — only after prompt is done

        round_id = await create_game_round(
            state['room_db_id'],
            state['round_number'],
            player_id,
        )
        state['current_round_db_id'] = round_id

        await self.broadcast('laugh_confirmed', {
            'player_id': player_id,
            'player_name': player['name'],
            'laugh_count': player['laugh_count'],
            'players': self.serialize_players(state),
        })

    async def start_next_round(self):
        state = ROOM_STATE[self.room_code]
        state['round_number'] += 1
        state['current_prompt'] = None
        state['laughed_player_id'] = None

        if state['mode'] == 'hotseat':
            hot_seat_id = state['player_order'][state['hot_seat_index']]
            hot_seat_name = state['players'][hot_seat_id]['name']
            await self.broadcast('round_start', {
                'round_number': state['round_number'],
                'hot_seat_player_id': hot_seat_id,
                'hot_seat_player_name': hot_seat_name,
                'mode': state['mode'],
                'players': self.serialize_players(state),
            })
        else:
            # first_laugh: all players monitored simultaneously
            await self.broadcast('round_start', {
                'round_number': state['round_number'],
                'hot_seat_player_id': None,
                'mode': state['mode'],
                'players': self.serialize_players(state),
            })

    async def advance_round(self, state):
        state['phase'] = 'playing'

        # Award bomb charges: survived means not the one who laughed
        laughed_id = state.get('laughed_player_id')
        for pid, p in state['players'].items():
            if pid != laughed_id:
                p['consecutive_survived'] += 1
                # Hot streak: 3 consecutive survived = double charge
                if p['consecutive_survived'] % 3 == 0:
                    p['bomb_charges'] += 2
                else:
                    p['bomb_charges'] += 1
                await update_player_stats(pid, p['laugh_count'], p['bomb_charges'], p['consecutive_survived'])

        # Advance hot seat index in hotseat mode
        if state['mode'] == 'hotseat' and state['player_order']:
            state['hot_seat_index'] = (state['hot_seat_index'] + 1) % len(state['player_order'])

        await self.broadcast('scores_update', {'players': self.serialize_players(state)})
        await self.start_next_round()

    async def get_prompt(self, state, kind: str) -> str:
        history = state['truth_history'] if kind == 'truth' else state['dare_history']
        content_mode = state['content_mode']

        # Try custom questions first if mode allows
        if content_mode in ('custom', 'merged'):
            customs = await get_custom_prompts(state['room_db_id'], kind)
            unused = [q for q in customs if q not in history]
            if unused and (content_mode == 'custom' or random.random() < 0.4):
                chosen = random.choice(unused)
                history.add(chosen)
                return chosen

        if content_mode == 'custom':
            return "No more custom questions! Add more in the menu."

        # Fetch from API with dedup
        for _ in range(5):
            q = fetch_prompt(kind)
            if q and q not in history:
                history.add(q)
                return q

        return f"No new {kind} available right now. Try again!"

    def get_player_by_face(self, state, face_index):
        for p in state['players'].values():
            if p['face_index'] == face_index:
                return p
        return None

    def serialize_players(self, state):
        return [
            {
                'id': p['id'],
                'name': p['name'],
                'face_index': p['face_index'],
                'laugh_count': p['laugh_count'],
                'bomb_charges': p['bomb_charges'],
                'consecutive_survived': p['consecutive_survived'],
            }
            for p in state['players'].values()
        ]

    async def send_state(self):
        state = ROOM_STATE.get(self.room_code, {})
        await self.send(text_data=json.dumps({
            'type': 'state_sync',
            'phase': state.get('phase', 'lobby'),
            'mode': state.get('mode'),
            'players': self.serialize_players(state),
            'round_number': state.get('round_number', 0),
        }))

    async def send_error(self, msg):
        await self.send(text_data=json.dumps({'type': 'error', 'message': msg}))

    async def broadcast(self, event_type, payload):
        await self.channel_layer.group_send(
            self.group_name,
            {'type': 'game_event', 'event_type': event_type, 'payload': payload}
        )

    async def game_event(self, event):
        await self.send(text_data=json.dumps({
            'type': event['event_type'],
            **event['payload'],
        }))

    @database_sync_to_async
    def create_player_db(self, room_id, name, face_index):
        from .models import Player
        p = Player.objects.create(room_id=room_id, name=name, face_index=face_index)
        return p.id

    @database_sync_to_async
    def save_custom_prompt(self, room_id, kind, text):
        from .models import CustomPrompt
        CustomPrompt.objects.create(room_id=room_id, kind=kind, text=text)
