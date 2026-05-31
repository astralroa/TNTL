import json
import os
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.core.files.base import ContentFile
from .models import Room, Player, LaughClip, GameRound, CustomPrompt
from .consumers import BOMB_ASSETS


def index(request):
    return render(request, 'game/index.html')


def create_room(request):
    if request.method == 'POST':
        mode = request.POST.get('mode', 'hotseat')
        content_mode = request.POST.get('content_mode', 'merged')
        room = Room.objects.create(mode=mode, content_mode=content_mode)
        return redirect('room', room_code=room.code)
    return render(request, 'game/create_room.html')


def join_room(request):
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        try:
            room = Room.objects.get(code=code, is_active=True)
            return redirect('room', room_code=room.code)
        except Room.DoesNotExist:
            return render(request, 'game/index.html', {'error': 'Room not found'})
    return redirect('index')


def room_view(request, room_code):
    room = get_object_or_404(Room, code=room_code, is_active=True)
    return render(request, 'game/room.html', {
        'room': room,
        'bomb_assets': json.dumps(BOMB_ASSETS),
    })


def end_screen(request, room_code):
    room = get_object_or_404(Room, code=room_code)
    players = Player.objects.filter(room=room).order_by('-laugh_count')
    clips = LaughClip.objects.filter(room=room).select_related('player', 'round')
    return render(request, 'game/end_screen.html', {
        'room': room,
        'players': players,
        'clips': clips,
    })


@csrf_exempt
@require_POST
def upload_clip(request, room_code):
    room = get_object_or_404(Room, code=room_code)
    player_id = request.POST.get('player_id')
    round_id = request.POST.get('round_id')
    clip_data = request.FILES.get('clip')

    if not clip_data or not player_id:
        return JsonResponse({'error': 'Missing data'}, status=400)

    try:
        player = Player.objects.get(id=player_id, room=room)
    except Player.DoesNotExist:
        return JsonResponse({'error': 'Player not found'}, status=404)

    game_round = None
    if round_id:
        try:
            game_round = GameRound.objects.get(id=round_id, room=room)
        except GameRound.DoesNotExist:
            pass

    clip = LaughClip.objects.create(
        room=room,
        player=player,
        round=game_round,
        clip_file=clip_data,
    )
    return JsonResponse({'clip_id': clip.id, 'url': clip.clip_file.url})


def api_clips(request, room_code):
    room = get_object_or_404(Room, code=room_code)
    clips = LaughClip.objects.filter(room=room).select_related('player')
    data = [
        {
            'id': c.id,
            'player_name': c.player.name,
            'url': c.clip_file.url,
            'created_at': c.created_at.isoformat(),
        }
        for c in clips
    ]
    return JsonResponse({'clips': data})


def api_bomb_assets(request):
    return JsonResponse(BOMB_ASSETS)
