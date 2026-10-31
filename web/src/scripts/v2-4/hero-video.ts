// WCAG 2.2.2 pause control for the hero loop. Does nothing until a <video data-hero-video> exists.
const video = document.querySelector<HTMLVideoElement>('video[data-hero-video]');
const btn = document.querySelector<HTMLButtonElement>('[data-hero-pause]');

if (video && btn) {
  const sync = () => {
    const paused = video.paused;
    btn.dataset.state = paused ? 'paused' : 'playing';
    btn.setAttribute('aria-label', paused ? 'Play background video' : 'Pause background video');
  };
  // Reduced motion: no autoplay, show the poster only.
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    video.removeAttribute('autoplay');
    video.pause();
    video.load();
  }
  video.addEventListener('play', sync);
  video.addEventListener('pause', sync);
  btn.addEventListener('click', () => {
    if (video.paused) video.play().catch(sync);
    else video.pause();
  });
  btn.hidden = false;
  sync();
}
