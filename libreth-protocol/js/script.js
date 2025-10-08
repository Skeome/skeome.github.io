const text = "ACCESS GRANTED :: VEIL_INTERFACE_7";
const typewriterElement = document.getElementById('typewriter');
let i = 0;
function typeWriter() {
    if (i < text.length) {
        typewriterElement.innerHTML += text.charAt(i);
        i++;
        setTimeout(typeWriter, 100);
    }
}
document.addEventListener('DOMContentLoaded', typeWriter);
