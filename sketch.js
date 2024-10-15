function setup() {
    createCanvas(windowWidth, windowHeight);
    audioContext = new AudioContext();
    analyzer = new AnalyserNode(audioContext);
    source = new AudioContext.createMediaElementSource(document.getElementById('audio-file'));
    source.connect(analyzer);
    analyzer.connect(audioContext.destination);
    fft = new FFT(analyzer.fftSize);
}

function draw() {
    background(0);
    fft.analyze();

    for (let i = 0; i < fft.spectrum.length; i++) {
        let amplitude = fft.spectrum[i];
        let barHeight = map(amplitude, 0, 255, 0, height);
        fill(255, 0, 0);
        rect(i * (width / fft.spectrum.length), height - barHeight, width / fft.spectrum.length, barHeight);
    }
}