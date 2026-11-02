/* Coach reaction overlay. Drop-in: include reactions.css + this file, then call
 *   CoachReactions.show(payload)   // payload from engine.fire()
 * or wire it to your socket:  socket.onmessage = e => { const m = JSON.parse(e.data);
 *   if (m.type === 'reaction') CoachReactions.show(m); }
 * Audio: browsers block autoplay until the user interacts once. Call
 * CoachReactions.unlock() from any click handler (your Start button is fine).
 */
(function (global) {
  const state = { host: null, timer: null, unlocked: false, queue: [], busy: false, log: [] };

  function host() {
    if (state.host) return state.host;
    const h = document.createElement("div");
    h.id = "coach-reaction-host";
    h.setAttribute("aria-live", "polite");
    document.body.appendChild(h);
    state.host = h;
    return h;
  }

  function unlock() {
    if (state.unlocked) return;
    const a = new Audio();
    a.muted = true;
    a.play().catch(() => {});
    state.unlocked = true;
  }

  function play(src, volume) {
    const a = new Audio(src);
    a.volume = Math.max(0, Math.min(1, volume == null ? 0.8 : volume));
    const p = a.play();
    if (p && p.catch) p.catch((err) => state.log.push("audio blocked: " + err.message));
    return a;
  }

  function render(p) {
    const h = host();
    h.innerHTML = "";
    const card = document.createElement("div");
    card.className = "coach-reaction";
    card.dataset.trigger = p.trigger;
    card.innerHTML =
      '<img class="coach-reaction__img" alt="">' +
      '<div class="coach-reaction__text"><div class="coach-reaction__tag">COACH</div>' +
      '<div class="coach-reaction__line"></div></div>';
    card.querySelector("img").src = p.image;
    card.querySelector(".coach-reaction__line").textContent = p.line || "";
    h.appendChild(card);
    requestAnimationFrame(() => card.classList.add("is-in"));
    if (p.sound) play(p.sound, p.volume);
    state.log.push("shown: " + p.trigger);
    return card;
  }

  function next() {
    if (state.busy || !state.queue.length) return;
    const p = state.queue.shift();
    state.busy = true;
    const card = render(p);
    const ms = p.show_ms || 2500;
    state.timer = setTimeout(() => {
      card.classList.remove("is-in");
      card.classList.add("is-out");
      setTimeout(() => {
        if (card.parentNode) card.parentNode.removeChild(card);
        state.busy = false;
        next();
      }, 260);
    }, ms);
  }

  function show(p) {
    if (!p || p.type !== "reaction") return false;
    if (state.queue.length >= 2) state.queue.shift(); // never pile up
    state.queue.push(p);
    next();
    return true;
  }

  global.CoachReactions = { show, unlock, _state: state };
})(window);
