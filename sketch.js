let song;
let amp;

function preload() {
    song=loadSound('Media/Audio/Journey to Another World.ogg');
}

function setup(){
    createCanvas(windowWidth, windowHeight);
    amp = new p5.Amplitude();
    song.play();
}

function draw(){
    background(0);
    let level = amp.getLevel();
    let size = map(level, 0, 1, 0, width/2);
    fill (255, 0, 0);
    ellipse(width/2, height/2, size, size);
}