// game.js — NoLaugh client-side game controller

(function () {
  // ── State ──────────────────────────────────────────────────────────────────
  let ws = null;
  let myPlayerId = null;
  let myFaceIndex = 0;
  let phase = 'lobby';
  let currentRoundId = null;
  let detector = null;
  let roller = null;
  let cameraStream = null;
  let selectedBombType = 'gif';
  let customModalKind = 'truth';
  let calInterval = null;

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const screens = {
    lobby:      document.getElementById('screen-lobby'),
    calibration:document.getElementById('screen-calibration'),
    game:       document.getElementById('screen-game'),
    truthDare:  document.getElementById('screen-truth-dare'),
    end:        document.getElementById('screen-end'),
  };

  // Single shared video + canvas — we move them into the right container
  const sharedVideo  = document.getElementById('shared-video');
  const sharedCanvas = document.getElementById('shared-canvas');

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    bindLobbyUI();
    bindGameUI();
    bindCustomModal();
  }

  // ── WebSocket ──────────────────────────────────────────────────────────────
  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/room/${ROOM_CODE}/`);
    ws.onopen = () => ws.send(JSON.stringify({ type: 'request_state' }));
    ws.onmessage = (e) => handleServerEvent(JSON.parse(e.data));
    ws.onclose = () => setTimeout(connectWS, 2000);
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  // ── Move shared video into a container ────────────────────────────────────
  function mountVideoIn(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    // Move elements into container
    container.appendChild(sharedVideo);
    container.appendChild(sharedCanvas);

    // Make sure they're visible
    sharedVideo.style.display = 'block';
    sharedCanvas.style.display = 'block';

    // Size the container to the video once ready
    function syncDimensions() {
      const w = sharedVideo.videoWidth || 640;
      const h = sharedVideo.videoHeight || 480;
      sharedVideo.style.width = '100%';
      sharedVideo.style.height = '100%';
      sharedCanvas.style.width = '100%';
      sharedCanvas.style.height = '100%';
      try {
        faceapi.matchDimensions(sharedCanvas, { width: w, height: h });
      } catch(e) {}
    }

    if (sharedVideo.readyState >= 1) {
      syncDimensions();
    } else {
      sharedVideo.addEventListener('loadedmetadata', syncDimensions, { once: true });
    }
  }

  // ── Server event handler ───────────────────────────────────────────────────
  function handleServerEvent(msg) {
    switch (msg.type) {
      case 'joined':
        myPlayerId = String(msg.player_id);
        if (!myPlayerIds.map(String).includes(String(msg.player_id))) {
          myPlayerIds.push(String(msg.player_id));
        }
        break;
      case 'player_joined':
      case 'player_left':
        renderLobbyPlayers(msg.players);
        updateStartBtn(msg.players);
        break;
      case 'calibration_start':
        startCalibrationPhase(msg);
        break;
      case 'round_start':
        startRound(msg);
        break;
      case 'laugh_confirmed':
        showTruthOrDare(msg);
        break;
      case 'prompt_assigned':
        showPrompt(msg);
        break;
      case 'scores_update':
        updateHUD(msg.players);
        break;
      case 'bomb_incoming':
        showBombIncoming(msg);
        break;
      case 'bomb_resolved':
        hideBombIncoming();
        break;
      case 'bomb_charged':
        updateHUD(msg.players);
        break;
      case 'state_sync':
        syncState(msg);
        break;
      case 'custom_prompt_saved':
        document.getElementById('custom-save-msg').textContent = `${msg.kind} saved!`;
        document.getElementById('custom-text').value = '';
        break;
      case 'error':
        alert(msg.message);
        break;
    }
  }

  // ── Lobby UI ───────────────────────────────────────────────────────────────
  // For local play, both players join from same browser tab.
  // myPlayerIds tracks all player IDs belonging to this tab.
  let myPlayerIds = [];
  let faceIndexP1 = 0;
  let faceIndexP2 = 1;
  let p1Joined = false;

  function bindLobbyUI() {
    // Face btn selection per player
    document.querySelectorAll('.face-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const playerNum = btn.dataset.player;
        document.querySelectorAll('.face-btn[data-player="' + playerNum + '"]')
          .forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        if (playerNum === '1') faceIndexP1 = parseInt(btn.dataset.face);
        else faceIndexP2 = parseInt(btn.dataset.face);
      });
    });

    // P1 join
    const joinBtnP1 = document.getElementById('join-btn-p1');
    if (joinBtnP1) {
      joinBtnP1.addEventListener('click', () => {
        const name = document.getElementById('player-name-p1').value.trim();
        if (!name) { alert('Enter Player 1 name'); return; }
        pendingJoin = 1;
        send({ type: 'join', name, face_index: ROOM_MODE === 'solo' ? 0 : faceIndexP1 });
      });
      document.getElementById('player-name-p1').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') joinBtnP1.click();
      });
    }

    // P2 join
    const joinBtnP2 = document.getElementById('join-btn-p2');
    if (joinBtnP2) {
      joinBtnP2.addEventListener('click', () => {
        const name = document.getElementById('player-name-p2').value.trim();
        if (!name) { alert('Enter Player 2 name'); return; }
        pendingJoin = 2;
        send({ type: 'join', name, face_index: faceIndexP2 });
      });
      document.getElementById('player-name-p2').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') joinBtnP2.click();
      });
    }

    document.getElementById('start-btn').addEventListener('click', () => {
      send({ type: 'start_game' });
    });
  }

  let pendingJoin = 1;

  function renderLobbyPlayers(players) {
    const el = document.getElementById('player-list-lobby');
    el.innerHTML = players.map(p => {
      const isMe = myPlayerIds.map(String).includes(String(p.id));
      const faceLabel = ROOM_MODE === 'solo' ? '' : ' — Face ' + (p.face_index + 1);
      return '<div class="lobby-player ' + (isMe ? 'me' : '') + '">' +
        p.name + faceLabel + (isMe ? ' (you)' : '') + '</div>';
    }).join('');
  }

  function updateStartBtn(players) {
    const btn = document.getElementById('start-btn');

    if (ROOM_MODE === 'solo') {
      // Solo: show start as soon as 1 player joined
      if (myPlayerIds.length >= 1) {
        hideEl('join-form-p1');
        btn.style.display = '';
      }
    } else {
      // Two-player: show P2 form after P1 joins, start after both join
      if (myPlayerIds.length === 1 && !p1Joined) {
        p1Joined = true;
        hideEl('join-form-p1');
        showEl('join-form-p2');
        document.getElementById('player-name-p2').focus();
      } else if (myPlayerIds.length >= 2 || players.length >= 2) {
        hideEl('join-form-p2');
        btn.style.display = '';
      }
    }
  }

  function hideEl(id) { const el = document.getElementById(id); if (el) el.style.display = 'none'; }
  function showEl(id) { const el = document.getElementById(id); if (el) el.style.display = ''; }

  // ── Calibration phase ──────────────────────────────────────────────────────
  async function startCalibrationPhase(msg) {
    showScreen('calibration');
    mountVideoIn('cal-video-slot');

    const msgEl = document.getElementById('calibration-msg');
    const statusEl = document.getElementById('cal-face-status');
    const bar = document.getElementById('cal-bar');
    const countdown = document.getElementById('cal-countdown');

    msgEl.textContent = 'Loading face detection models...';
    if (statusEl) statusEl.textContent = '(first load may take a few seconds)';

    try {
      detector = new LaughDetector({
        onLaugh: handleLaughDetected,
        onFacesUpdate: updateCalibrationUI,
      });

      // Load models — this can take a few seconds on first run (CDN download)
      await detector.loadModels();
      cameraStream = await detector.startCamera(sharedVideo, sharedCanvas);
      roller = new RollingRecorder(cameraStream);

      // Models ready — now start the visible countdown
      msgEl.textContent = msg.message || 'Look neutral at the camera...';
      if (statusEl) statusEl.textContent = 'Detecting faces...';

      const duration = (msg.duration || 10) * 1000;
      let elapsed = 0;

      // Start countdown timer
      bar.style.width = '0%';
      countdown.textContent = Math.ceil(duration / 1000);
      calInterval = setInterval(() => {
        elapsed += 100;
        const pct = Math.min(elapsed / duration * 100, 100);
        bar.style.width = pct + '%';
        countdown.textContent = Math.max(0, Math.ceil((duration - elapsed) / 1000));
      }, 100);

      // Run calibration — this Promise resolves when duration is up
      const thresholds = await detector.startCalibration(duration);
      clearInterval(calInterval);
      bar.style.width = '100%';
      countdown.textContent = '0';

      // Show result
      if (statusEl) {
        const parts = Object.entries(thresholds).map(([i, t]) =>
          'Face ' + (parseInt(i) + 1) + ': ' + (t.happy * 100).toFixed(0) + '%'
        );
        statusEl.textContent = parts.length
          ? '✓ Done — ' + parts.join(' | ')
          : '⚠ No faces detected — using defaults (watch out for false positives)';
      }

      // Small pause so player can read the result
      await new Promise(r => setTimeout(r, 800));

      send({
        type: 'calibration_done',
        threshold: thresholds[0]?.happy || 0.25,
        all_player_ids: myPlayerIds,
      });

    } catch (err) {
      clearInterval(calInterval);
      console.error('Calibration error:', err);
      alert('Camera error: ' + err.message);
    }
  }

  function updateCalibrationUI(faces) {
    const el = document.getElementById('cal-face-status');
    if (!el) return;
    if (!faces.length) {
      el.textContent = '⚠️ No face detected — make sure you\'re in frame';
      return;
    }
    el.textContent = '✓ ' + faces.length + ' face' + (faces.length > 1 ? 's' : '') + ' detected';
  }

  // ── Round start ────────────────────────────────────────────────────────────
  function startRound(msg) {
    phase = 'playing';
    showScreen('game');

    // Move shared video into game screen slot
    mountVideoIn('game-video-slot');

    // Update detector to use shared elements (they're the same objects, but re-sync canvas)
    if (detector) {
      detector.video = sharedVideo;
      detector.canvas = sharedCanvas;
      if (sharedVideo.videoWidth) {
        faceapi.matchDimensions(sharedCanvas, {
          width: sharedVideo.videoWidth,
          height: sharedVideo.videoHeight
        });
      }
    }

    document.getElementById('round-number').textContent = 'Round ' + msg.round_number;

    if (msg.mode === 'hotseat' && msg.hot_seat_player_id) {
      const label = document.getElementById('hot-seat-label');
      label.textContent = 'Hot Seat: ' + msg.hot_seat_player_name;
      label.className = String(msg.hot_seat_player_id) === String(myPlayerId) ? 'hot-seat-me' : 'hot-seat-other';
    } else if (msg.mode === 'solo') {
      document.getElementById('hot-seat-label').textContent = 'Try not to laugh 😐';
    } else {
      document.getElementById('hot-seat-label').textContent = 'Everyone on edge 👀';
    }

    updateHUD(msg.players);

    if (detector && !detector.running) {
      detector.startDetection();
    }

    if (roller && !roller.active) {
      roller.start();
    }

    currentRoundId = null;
  }

  // ── Laugh detected (client-side) ──────────────────────────────────────────
  function handleLaughDetected(faceIndex) {
    if (phase !== 'playing') return;
    send({ type: 'laugh_detected', face_index: faceIndex });
  }

  // Track which player is currently in the hot seat for truth/dare
  let currentLaughedPlayerId = null;

  // ── Truth or Dare screen ───────────────────────────────────────────────────
  function showTruthOrDare(msg) {
    phase = 'truth_dare';
    // Normalize to string for consistent comparison
    currentLaughedPlayerId = String(msg.player_id);

    if (roller && myPlayerIds.map(String).includes(currentLaughedPlayerId)) {
      const blob = roller.triggerCapture();
      if (blob) {
        uploadLaughClip(ROOM_CODE, currentLaughedPlayerId, null, blob, roller.getExtension());
      }
    }

    if (detector) detector.stopDetection();

    showScreen('truthDare');

    const announcement = document.getElementById('laugh-announcement');
    const isLocalPlayerLaughing = myPlayerIds.map(String).includes(currentLaughedPlayerId);

    // Find the specific laughing player's name
    const laughingName = msg.player_name || 'Someone';

    if (isLocalPlayerLaughing) {
      announcement.textContent = '😂 ' + laughingName + ' laughed! Choose your fate.';
      announcement.className = 'laugh-announcement me';
    } else {
      announcement.textContent = '😂 ' + laughingName + ' laughed!';
      announcement.className = 'laugh-announcement other';
    }

    // Enable buttons — always show them so both players can interact locally
    document.getElementById('choose-truth-btn').disabled = false;
    document.getElementById('choose-dare-btn').disabled = false;
    document.getElementById('choose-truth-btn').style.display = '';
    document.getElementById('choose-dare-btn').style.display = '';
    document.getElementById('prompt-display').classList.add('hidden');
  }

  function showPrompt(msg) {
    const display = document.getElementById('prompt-display');
    const kindBadge = document.getElementById('prompt-kind-badge');
    const text = document.getElementById('prompt-text');

    kindBadge.textContent = msg.kind === 'truth' ? '🔥 TRUTH' : '😈 DARE';
    kindBadge.className = 'prompt-badge ' + msg.kind;
    text.textContent = msg.text;

    display.classList.remove('hidden');
    document.getElementById('choose-truth-btn').style.display = 'none';
    document.getElementById('choose-dare-btn').style.display = 'none';

    // Always show done button for local play — anyone can press it
    document.getElementById('prompt-done-btn').style.display = '';
  }

  // ── HUD ───────────────────────────────────────────────────────────────────
  function updateHUD(players) {
    const hud = document.getElementById('players-hud');
    hud.innerHTML = players.map(p =>
      '<div class="player-hud-card ' + (String(p.id) === String(myPlayerId) ? 'me' : '') + '">' +
        '<span class="pname">' + p.name + '</span>' +
        '<span class="plaughs">😂 ' + p.laugh_count + '</span>' +
        '<span class="pbombs">💣 ' + p.bomb_charges + '</span>' +
        (p.consecutive_survived >= 2 ? '<span class="pstreak">🔥</span>' : '') +
      '</div>'
    ).join('');

    const myPlayer = players.find(p => p.id == myPlayerId);
    const launcher = document.getElementById('bomb-launcher');
    if (myPlayer && myPlayer.bomb_charges > 0 && phase === 'playing') {
      launcher.classList.remove('hidden');
    } else {
      launcher.classList.add('hidden');
    }
  }

  // ── Bomb launcher ─────────────────────────────────────────────────────────
  function bindGameUI() {
    document.getElementById('choose-truth-btn').addEventListener('click', () => {
      send({ type: 'choose_prompt', kind: 'truth' });
    });
    document.getElementById('choose-dare-btn').addEventListener('click', () => {
      send({ type: 'choose_prompt', kind: 'dare' });
    });

    document.getElementById('prompt-done-btn').addEventListener('click', () => {
      send({ type: 'prompt_done' });
      // Detection restarts on next round_start from server
    });

    document.querySelectorAll('.bomb-type-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.bomb-type-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        selectedBombType = btn.dataset.type;
      });
    });

    document.getElementById('fire-bomb-btn').addEventListener('click', () => {
      send({ type: 'bomb_fire', bomb_type: selectedBombType });
    });

    document.getElementById('end-game-btn').addEventListener('click', () => {
      if (confirm('End the game?')) {
        location.href = '/room/' + ROOM_CODE + '/end/';
      }
    });

    document.getElementById('bomb-incoming').addEventListener('click', () => {
      send({ type: 'bomb_resolved' });
      hideBombIncoming();
    });
  }

  function showBombIncoming(msg) {
    const container = document.getElementById('bomb-incoming');
    document.getElementById('bomb-attacker-label').textContent =
      '💣 ' + msg.attacker_name + ' fired a bomb!';

    const area = document.getElementById('bomb-media-area');
    area.innerHTML = '';

    if (msg.bomb_type === 'gif') {
      const img = document.createElement('img');
      img.src = msg.asset.url;
      img.alt = msg.asset.label;
      img.className = 'bomb-gif';
      area.appendChild(img);
    } else if (msg.bomb_type === 'sound') {
      const audio = new Audio(msg.asset.url);
      audio.play().catch(() => {});
      const label = document.createElement('div');
      label.className = 'bomb-sound-label';
      label.textContent = '🔊 ' + msg.asset.label;
      area.appendChild(label);
    }

    container.classList.remove('hidden');
    setTimeout(() => {
      send({ type: 'bomb_resolved' });
      hideBombIncoming();
    }, 4000);
  }

  function hideBombIncoming() {
    document.getElementById('bomb-incoming').classList.add('hidden');
    document.getElementById('bomb-media-area').innerHTML = '';
  }

  // ── Custom question modal ─────────────────────────────────────────────────
  function bindCustomModal() {
    document.getElementById('open-custom-btn').addEventListener('click', () => {
      document.getElementById('custom-modal').classList.remove('hidden');
    });
    document.getElementById('close-custom-btn').addEventListener('click', () => {
      document.getElementById('custom-modal').classList.add('hidden');
    });
    document.querySelectorAll('.type-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.type-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        customModalKind = btn.dataset.kind;
      });
    });
    document.getElementById('save-custom-btn').addEventListener('click', () => {
      const text = document.getElementById('custom-text').value.trim();
      if (!text) return;
      send({ type: 'add_custom_prompt', kind: customModalKind, text });
    });
  }

  // ── State sync ────────────────────────────────────────────────────────────
  function syncState(msg) {
    phase = msg.phase;
    if (msg.phase === 'lobby') showScreen('lobby');
    else if (msg.phase === 'calibration') showScreen('calibration');
    else if (msg.phase === 'playing') showScreen('game');
    else if (msg.phase === 'truth_dare') showScreen('truthDare');
    if (msg.players) updateHUD(msg.players);
  }

  // ── Screen manager ────────────────────────────────────────────────────────
  function showScreen(name) {
    Object.values(screens).forEach(s => s && s.classList.remove('active'));
    if (screens[name]) screens[name].classList.add('active');
  }

  // ── Start ─────────────────────────────────────────────────────────────────
  connectWS();
  init();

})();
