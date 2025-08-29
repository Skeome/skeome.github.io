let song;
let fft;
let smoothing = 0.8;
let bins = 512;
let waveform = [];
let r = 100;

function preload() {
  song = loadSound("Media/Audio/Journey-to-Another-World.wav");
}

function setup() {
  createCanvas(400, 400);
  fft = new p5.FFT(smoothing, bins);
}

function draw() {
  background(220);
  waveform = fft.waveform();

  for (let i = 0; i < waveform.length; i++) {
    let y = height / 2 + map(waveform[i], -1, 1, -r, r);
    ellipse(i, y, 1, 1);
  }
}

function mousePressed() {
  if (!song.isPlaying()) {
    song.play();
  }
}