from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('create/', views.create_room, name='create_room'),
    path('join/', views.join_room, name='join_room'),
    path('room/<str:room_code>/', views.room_view, name='room'),
    path('room/<str:room_code>/end/', views.end_screen, name='end_screen'),
    path('room/<str:room_code>/upload-clip/', views.upload_clip, name='upload_clip'),
    path('api/room/<str:room_code>/clips/', views.api_clips, name='api_clips'),
    path('api/bomb-assets/', views.api_bomb_assets, name='api_bomb_assets'),
]
