// laugh_detection.js
const MODELS_URL = 'https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.13/model';

class LaughDetector {
  constructor({ onLaugh, onFacesUpdate }) {
    this.onLaugh = onLaugh;
    this.onFacesUpdate = onFacesUpdate;

    this.modelsLoaded = false;
    this.running = false;
    this.video = null;
    this.canvas = null;
    this.animFrame = null;

    this.baselines = {};
    this.thresholds = {};
    this.lastLaughTime = {};
    this.DEBOUNCE_MS = 600;

    this.calibSamples = {};
    this.calibrating = false;
  }

  async loadModels() {
    if (this.modelsLoaded) return;
    await Promise.all([
      faceapi.nets.tinyFaceDetector.loadFromUri(MODELS_URL),
      faceapi.nets.faceExpressionNet.loadFromUri(MODELS_URL),
      faceapi.nets.faceLandmark68TinyNet.loadFromUri(MODELS_URL),
    ]);
    this.modelsLoaded = true;
  }

  async startCamera(videoEl, canvasEl) {
    this.video = videoEl;
    this.canvas = canvasEl;
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: 'user' },
      audio: false,
    });
    videoEl.srcObject = stream;
    await new Promise((resolve, reject) => {
      videoEl.onloadedmetadata = resolve;
      videoEl.onerror = reject;
    });
    await videoEl.play();
    faceapi.matchDimensions(canvasEl, {
      width: videoEl.videoWidth,
      height: videoEl.videoHeight,
    });
    return stream;
  }

  // ── CALIBRATION ─────────────────────────────────────────────────────────
  // Returns a Promise that resolves with thresholds after durationMs.
  startCalibration(durationMs = 10000) {
    this.calibrating = true;
    this.calibSamples = {};

    return new Promise((resolve) => {
      const deadline = Date.now() + durationMs;

      const tick = async () => {
        if (!this.calibrating) {
          resolve(this._computeThresholds());
          return;
        }

        if (Date.now() >= deadline) {
          this.calibrating = false;
          resolve(this._computeThresholds());
          return;
        }

        const detections = await this._detect();
        detections.forEach((det, i) => {
          if (!this.calibSamples[i]) this.calibSamples[i] = [];
          const happy = det.expressions.happy;
          const mouth = this._mouthOpenness(det.landmarks);
          this.calibSamples[i].push({ happy, mouth });
        });

        setTimeout(tick, 100);
      };

      tick();
    });
  }

  // Call this to get thresholds — safe to call even if calibration is still running
  _computeThresholds() {
    this.calibrating = false;
    const thresholds = {};
    for (const [idx, samples] of Object.entries(this.calibSamples)) {
      if (!samples.length) continue;
      const happyVals = samples.map(s => s.happy);
      const mouthVals = samples.map(s => s.mouth);
      const hMean = mean(happyVals);
      const hStd  = std(happyVals);
      const mMean = mean(mouthVals);
      const mStd  = std(mouthVals);

      this.baselines[idx] = { happyMean: hMean, happyStd: hStd, mouthMean: mMean, mouthStd: mStd };
      this.thresholds[idx] = {
        happy: Math.min(Math.max(hMean + 1.5 * hStd, 0.15), 0.45),
        mouth: Math.min(Math.max(mMean + 1.5 * mStd, 0.08), 0.35),
      };
      thresholds[idx] = this.thresholds[idx];
    }
    return thresholds;
  }

  // Keep finishCalibration as alias for backwards compat
  finishCalibration() {
    return this._computeThresholds();
  }

  // ── DETECTION LOOP ───────────────────────────────────────────────────────
  startDetection() {
    this.running = true;
    this._detectionLoop();
  }

  stopDetection() {
    this.running = false;
    if (this.animFrame) cancelAnimationFrame(this.animFrame);
  }

  async _detectionLoop() {
    if (!this.running) return;

    const detections = await this._detect();
    const ctx = this.canvas.getContext('2d');
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    const faceData = [];
    detections.forEach((det, i) => {
      this._drawFaceBox(ctx, det, i);
      const happy = det.expressions.happy;
      const mouth = this._mouthOpenness(det.landmarks);
      faceData.push({ index: i, happy, mouth, box: det.detection.box });

      const thresh = this.thresholds[i];
      if (!thresh) return;

      const isLaughing = happy > thresh.happy && mouth > thresh.mouth;
      const now = Date.now();
      const lastLaugh = this.lastLaughTime[i] || 0;

      if (isLaughing && (now - lastLaugh) > this.DEBOUNCE_MS) {
        this.lastLaughTime[i] = now;
        if (this.onLaugh) this.onLaugh(i);
      }
    });

    if (this.onFacesUpdate) this.onFacesUpdate(faceData);

    this.animFrame = requestAnimationFrame(() => this._detectionLoop());
  }

  async _detect() {
    if (!this.video || this.video.readyState < 2) return [];
    try {
      const results = await faceapi
        .detectAllFaces(this.video, new faceapi.TinyFaceDetectorOptions({ inputSize: 320 }))
        .withFaceLandmarks(true)
        .withFaceExpressions();
      return results || [];
    } catch (e) {
      return [];
    }
  }

  _mouthOpenness(landmarks) {
    if (!landmarks) return 0;
    try {
      const pts = landmarks.positions;
      const upperLip = pts[62];
      const lowerLip = pts[66];
      const leftMouth = pts[48];
      const rightMouth = pts[54];
      const mouthHeight = Math.abs(lowerLip.y - upperLip.y);
      const mouthWidth = Math.abs(rightMouth.x - leftMouth.x);
      return mouthWidth > 0 ? mouthHeight / mouthWidth : 0;
    } catch (e) {
      return 0;
    }
  }

  _drawFaceBox(ctx, det, faceIndex) {
    const box = det.detection.box;
    const thresh = this.thresholds[faceIndex];
    const happy = det.expressions.happy;
    const isLaughing = thresh && happy > thresh.happy;

    ctx.strokeStyle = isLaughing ? '#ff3b3b' : '#00e676';
    ctx.lineWidth = 3;
    ctx.strokeRect(box.x, box.y, box.width, box.height);

    ctx.fillStyle = isLaughing ? '#ff3b3b' : '#00e676';
    ctx.font = 'bold 14px monospace';
    ctx.fillText(
      'Face ' + (faceIndex + 1) + '  \uD83D\uDE0A' + (happy * 100).toFixed(0) + '%',
      box.x + 4, box.y - 8
    );
  }

  destroy() {
    this.stopDetection();
    if (this.video && this.video.srcObject) {
      this.video.srcObject.getTracks().forEach(t => t.stop());
    }
  }
}

function mean(arr) {
  return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
}
function std(arr) {
  if (arr.length < 2) return 0.05;
  const m = mean(arr);
  return Math.sqrt(arr.reduce((a, b) => a + (b - m) ** 2, 0) / arr.length);
}
