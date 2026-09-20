export function createRectCache(element: HTMLElement | HTMLCanvasElement) {
  let rect = element.getBoundingClientRect();
  const update = () => {
    rect = element.getBoundingClientRect();
  };
  window.addEventListener("resize", update, { passive: true });
  window.addEventListener("scroll", update, { passive: true });
  return {
    get current() {
      return rect;
    },
    destroy() {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update);
    },
  };
}
