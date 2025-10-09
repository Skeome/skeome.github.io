(function () {
  const loading = document.getElementById('loading-screen');
  const entry = document.getElementById('entry');
  const enterBtn = document.getElementById('enter');
  const lines = Array.from(document.querySelectorAll('.boot .line'));
  const bar = document.querySelector('.progress > span');
  const flashEl = document.querySelector('.flash');

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const typeSpeed = reduceMotion ? 0 : 12;        // ms/char
  const betweenLines = reduceMotion ? 0 : 120;    // ms
  const totalBootMs = 4000;
  let skipped = false;

  // --- tiny audio helpers ---
  let audioCtx;
  function getCtx() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    return audioCtx;
  }
  function beep(f = 560, ms = 120, type = 'sine', gain = 0.04) {
    try {
      const ctx = getCtx();
      const t0 = ctx.currentTime;
      const osc = ctx.createOscillator();
      const g = ctx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(f, t0);
      g.gain.setValueAtTime(0, t0);
      g.gain.linearRampToValueAtTime(gain, t0 + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + ms / 1000);
      osc.connect(g).connect(ctx.destination);
      osc.start(t0);
      osc.stop(t0 + ms / 1000);
    } catch (_) {}
  }
  function thump(ms = 120, gain = 0.07) {
    try {
      const ctx = getCtx();
      const t0 = ctx.currentTime;
      const buffer = ctx.createBuffer(1, ctx.sampleRate * (ms / 1000), ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length);
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      const g = ctx.createGain();
      g.gain.setValueAtTime(gain, t0);
      const biquad = ctx.createBiquadFilter();
      biquad.type = 'lowpass';
      biquad.frequency.setValueAtTime(220, t0);
      src.connect(biquad).connect(g).connect(ctx.destination);
      src.start(t0);
      src.stop(t0 + ms / 1000);
    } catch (_) {}
  }

  // --- ASCII distortion: briefly garble random characters, then restore ---
  function distortTextOnce(el, duration = 110) {
    if (reduceMotion) return Promise.resolve();
    return new Promise(resolve => {
      const original = el.textContent;
      const chars = original.split('');
      const noise = '▒#?ΣΩ∆¤ΨΞ';
      const pick = () => noise[Math.floor(Math.random() * noise.length)];
      // produce a masked version: randomly replace ~12% of visible chars
      const scrambled = chars.map(ch => {
        if (/\s/.test(ch)) return ch;
        return Math.random() < 0.12 ? pick() : ch;
      }).join('');
      el.textContent = scrambled;
      setTimeout(() => { el.textContent = original; resolve(); }, duration);
    });
  }

  // --- typewriter ---
  const snapshots = lines.map(el => el.textContent);
  function typeLine(el, fullText) {
    return new Promise(resolve => {
      el.classList.add('typing');
      if (typeSpeed === 0 || fullText.length === 0) {
        el.textContent = fullText;
        el.classList.remove('typing');
        return resolve();
      }
      el.textContent = '';
      let i = 0;
      const tick = () => {
        if (skipped) { el.textContent = fullText; el.classList.remove('typing'); return resolve(); }
        el.textContent += fullText.charAt(i++);
        if (i < fullText.length) setTimeout(tick, typeSpeed);
        else { el.classList.remove('typing'); resolve(); }
      };
      tick();
    });
  }

  async function playBoot() {
    const start = performance.now();

    // progress bar synced via JS (so skip is instant)
    (function progressTick() {
      if (skipped) return;
      const t = Math.min((performance.now() - start) / totalBootMs, 1);
      bar.style.width = (t * 100).toFixed(2) + '%';
      if (t < 1) requestAnimationFrame(progressTick);
    })();

    // little “boot” beep at start
    beep(540, 90);

    for (let idx = 0; idx < lines.length; idx++) {
      const el = lines[idx];
      const text = snapshots[idx];
      el.classList.add('revealed');

      // type it
      await typeLine(el, text);

      // brief ASCII distortion on some lines (skip blank spacer)
      if (!skipped && text.trim().length && idx !== lines.length - 1) {
        await distortTextOnce(el, 110);
      }

      if (skipped) break;
      if (betweenLines) await new Promise(r => setTimeout(r, betweenLines));
    }

    if (!skipped) {
      bar.style.width = '100%';
      // end-of-boot confirmation ping
      beep(720, 100);

      // 1) GLITCH TEAR just before reveal
      await doTear();

      // 2) FLASH as entry appears
      doFlash();

      setTimeout(showEntry, reduceMotion ? 0 : 80);
    }
  }

  // add/remove the 'tear' class for a quick jitter burst
  function doTear() {
    return new Promise(resolve => {
      if (reduceMotion) return resolve();
      loading.classList.add('tear');
      setTimeout(() => {
        loading.classList.remove('tear');
        resolve();
      }, 180);
    });
  }

  // trigger the flash overlay
  function doFlash() {
    if (reduceMotion || !flashEl) return;
    flashEl.classList.remove('go'); // reset if needed
    // force reflow to restart animation if repeated
    void flashEl.offsetWidth;
    flashEl.classList.add('go');
  }

  function showEntry() {
    loading.style.opacity = '0';
    loading.style.pointerEvents = 'none';
    entry.setAttribute('aria-hidden', 'false');
    entry.style.opacity = '1';
  }

  function skip() {
    if (skipped) return;
    skipped = true;
    lines.forEach((el, i) => {
      el.classList.add('revealed');
      el.classList.remove('typing');
      el.textContent = snapshots[i];
    });
    bar.style.width = '100%';
    beep(760, 90);
    showEntry();
  }

  // entry hidden at start
  entry.style.opacity = '0';

  // allow skip (first interaction also unlocks audio context on some browsers)
  window.addEventListener('keydown', skip, { once: true });
  window.addEventListener('click', skip,   { once: true });

  // play boot
  playBoot();

  // handle “LISTEN” click with a tiny thump, then navigate
  enterBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    thump(120, 0.08);
    setTimeout(() => { location.href = 'collapse.html'; }, 120);
  });
})();
