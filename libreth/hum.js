// hum.js — persistent hum at –9 dB, no user controls
(function () {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let ctx, master, running = false;
  const volDb = -12; // fixed default
  const db2gain = db => Math.pow(10, db / 20);

  function ensureCtx() {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    return ctx;
  }

  function makeNoise(seconds = 2) {
    const c = ensureCtx();
    const buffer = c.createBuffer(1, c.sampleRate * seconds, c.sampleRate);
    const data = buffer.getChannelData(0);
    let last = 0;
    for (let i = 0; i < data.length; i++) {
      const white = Math.random() * 2 - 1;
      last = (last + 0.02 * white) / 1.02;
      data[i] = last;
    }
    const src = c.createBufferSource();
    src.buffer = buffer;
    src.loop = true;
    return src;
  }

  function initGraph() {
    const c = ensureCtx();
    master = c.createGain();
    master.gain.value = db2gain(volDb);
    const comp = c.createDynamicsCompressor();
    comp.threshold.value = -24;
    comp.knee.value = 20;
    comp.ratio.value = 3;
    comp.attack.value = 0.003;
    comp.release.value = 0.25;
    master.connect(comp).connect(c.destination);

    const tones = [
      { f: 110, t: 'sine', g: 0.06 },
      { f: 220, t: 'triangle', g: 0.045 },
      { f: 440, t: 'sine', g: 0.02 }
    ];

    tones.forEach(({ f, t, g }) => {
      const o = c.createOscillator();
      o.type = t;
      o.frequency.value = f;
      const gain = c.createGain(); gain.gain.value = g;
      o.connect(gain).connect(master);
      o.start();
    });

    const noise = makeNoise(2);
    const bp = c.createBiquadFilter();
    bp.type = 'bandpass';
    bp.frequency.value = 180;
    bp.Q.value = 0.7;
    const gn = c.createGain(); gn.gain.value = 0.015;
    noise.connect(bp).connect(gn).connect(master);
    noise.start();
  }

  async function startHum() {
    if (running || reduceMotion) return;
    initGraph();
    try { await ctx.resume(); } catch {}
    running = true;
  }

  // start on first user interaction
  window.addEventListener('click', () => startHum(), { once: true });
  window.addEventListener('keydown', () => startHum(), { once: true });
})();
