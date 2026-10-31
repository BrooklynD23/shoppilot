// Landing footage: each [data-vid] plays only while on screen, never under reduced motion
// (CSS shows the poster instead), and has a Pause toggle (aria-pressed = paused by you).
// The morning clip is preload="none": nothing downloads until it scrolls into view.
const reduce = matchMedia('(prefers-reduced-motion: reduce)');

document.querySelectorAll<HTMLElement>('[data-vid]').forEach((box) => {
  const video = box.querySelector('video');
  const btn = box.querySelector<HTMLButtonElement>('[data-vid-btn]');
  if (!video || !btn) return;
  box.querySelector('[data-vid-css]')?.remove(); // the no-JS checkbox; the real button takes over

  let paused = false;
  let visible = false;

  const sync = () => {
    btn.hidden = reduce.matches;
    btn.setAttribute('aria-pressed', String(paused));
    if (visible && !paused && !reduce.matches) {
      video.play().catch(() => { /* autoplay refused: the poster stays, which is fine */ });
    } else {
      video.pause();
    }
  };

  btn.addEventListener('click', () => { paused = !paused; sync(); });
  reduce.addEventListener('change', sync);
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; sync(); }, { rootMargin: '120px 0px' }).observe(box);
  btn.hidden = reduce.matches; // first sync runs on the observer's initial callback
});
