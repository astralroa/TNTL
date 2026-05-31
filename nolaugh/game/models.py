from django.db import models
import random
import string


def gen_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


class Room(models.Model):
    MODE_SOLO = 'solo'
    MODE_HOTSEAT = 'hotseat'
    MODE_FIRST_LAUGH = 'first_laugh'
    MODE_CHOICES = [
        (MODE_SOLO, 'Solo'),
        (MODE_HOTSEAT, 'Two Players — Hotseat Rotation'),
        (MODE_FIRST_LAUGH, 'Two Players — First to Laugh Loses'),
    ]

    CONTENT_CUSTOM = 'custom'
    CONTENT_MERGED = 'merged'
    CONTENT_API = 'api'
    CONTENT_CHOICES = [
        (CONTENT_CUSTOM, 'Custom Only'),
        (CONTENT_MERGED, 'Merged'),
        (CONTENT_API, 'API Only'),
    ]

    code = models.CharField(max_length=6, unique=True, default=gen_room_code)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_HOTSEAT)
    content_mode = models.CharField(max_length=10, choices=CONTENT_CHOICES, default=CONTENT_MERGED)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Room {self.code} ({self.mode})"


class Player(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='players')
    name = models.CharField(max_length=50)
    face_index = models.IntegerField(default=0)  # 0 or 1, which detected face belongs to this player
    laugh_count = models.IntegerField(default=0)
    bomb_charges = models.IntegerField(default=0)
    consecutive_survived = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} in {self.room.code}"


class CustomPrompt(models.Model):
    KIND_TRUTH = 'truth'
    KIND_DARE = 'dare'
    KIND_CHOICES = [(KIND_TRUTH, 'Truth'), (KIND_DARE, 'Dare')]

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='custom_prompts')
    kind = models.CharField(max_length=5, choices=KIND_CHOICES)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.kind}: {self.text[:50]}"


class GameRound(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='rounds')
    round_number = models.IntegerField(default=1)
    hot_seat_player = models.ForeignKey(Player, on_delete=models.SET_NULL, null=True, related_name='hot_seat_rounds')
    prompt_text = models.TextField(blank=True)
    prompt_type = models.CharField(max_length=5, blank=True)  # truth/dare
    laugh_detected_at = models.DateTimeField(null=True, blank=True)
    completed = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Round {self.round_number} in {self.room.code}"


class LaughBomb(models.Model):
    TYPE_GIF = 'gif'
    TYPE_SOUND = 'sound'
    TYPE_CHOICES = [(TYPE_GIF, 'GIF'), (TYPE_SOUND, 'Sound')]

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='bombs')
    owner = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='bombs_fired')
    bomb_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    asset_id = models.CharField(max_length=100)
    fired_at_round = models.ForeignKey(GameRound, on_delete=models.SET_NULL, null=True)
    fired_at = models.DateTimeField(auto_now_add=True)


class LaughClip(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='clips')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='clips')
    round = models.ForeignKey(GameRound, on_delete=models.SET_NULL, null=True)
    clip_file = models.FileField(upload_to='laugh_clips/')
    created_at = models.DateTimeField(auto_now_add=True)
