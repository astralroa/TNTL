// media_recorder.js
// Maintains a rolling 3-second pre-laugh buffer.
// When triggerCapture() is called, stitches the buffer into a Blob and returns it.

class RollingRecorder {
  constructor(stream, { bufferSeconds = 3, mimeType = '' } = {}) {
    this.stream = stream;
    this.bufferSeconds = bufferSeconds;
    this.chunks = [];       // { blob, timestamp }
    this.recorder = null;
    this.active = false;

    // Pick best supported mime type
    const candidates = ['video/webm;codecs=vp8', 'video/webm', 'video/mp4'];
    this.mimeType = mimeType || candidates.find(m => MediaRecorder.isTypeSupported(m)) || '';
  }

  start() {
    if (this.active) return;
    try {
      const opts = this.mimeType ? { mimeType: this.mimeType } : {};
      this.recorder = new MediaRecorder(this.stream, opts);
      this.recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          this.chunks.push({ blob: e.data, timestamp: Date.now() });
          this._prune();
        }
      };
      // Timeslice: collect every 500ms for a rolling window
      this.recorder.start(500);
      this.active = true;
    } catch (e) {
      console.warn('RollingRecorder start failed:', e);
    }
  }

  stop() {
    if (!this.active) return;
    try {
      this.recorder.stop();
    } catch (e) {}
    this.active = false;
    this.chunks = [];
  }

  // Call this when a laugh is confirmed.
  // Returns a Blob of the last `bufferSeconds` of footage.
  triggerCapture() {
    this._prune();
    const blobs = this.chunks.map(c => c.blob);
    if (!blobs.length) return null;
    const type = this.mimeType || 'video/webm';
    return new Blob(blobs, { type });
  }

  _prune() {
    const cutoff = Date.now() - (this.bufferSeconds * 1000);
    // Keep at least last bufferSeconds worth of chunks
    // But always keep the last 2 chunks minimum in case of slow timeslices
    while (this.chunks.length > 2 && this.chunks[0].timestamp < cutoff) {
      this.chunks.shift();
    }
  }

  getExtension() {
    if (this.mimeType.includes('mp4')) return 'mp4';
    return 'webm';
  }
}


// Upload a Blob to the server as a laugh clip
async function uploadLaughClip(roomCode, playerId, roundId, blob, extension) {
  const formData = new FormData();
  formData.append('player_id', playerId);
  formData.append('round_id', roundId || '');
  formData.append('clip', blob, `laugh_${playerId}_${Date.now()}.${extension}`);

  // Get CSRF token from cookie
  const csrf = getCookie('csrftoken');

  try {
    const resp = await fetch(`/room/${roomCode}/upload-clip/`, {
      method: 'POST',
      headers: csrf ? { 'X-CSRFToken': csrf } : {},
      body: formData,
    });
    if (resp.ok) {
      const data = await resp.json();
      return data;
    }
  } catch (e) {
    console.warn('Clip upload failed:', e);
  }
  return null;
}

function getCookie(name) {
  const val = document.cookie.split('; ').find(r => r.startsWith(name + '='));
  return val ? val.split('=')[1] : '';
}
