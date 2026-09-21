import { createEffect, createSignal, onCleanup, Show, untrack } from "solid-js"
import { Markdown } from "./components"

// The server publishes change notices and complete text snapshots, not replayable token deltas.
// Preserve the displayed prefix across message refreshes so a remount cannot restart the reveal.
export default function SmoothMarkdown(props: { text: string; live: boolean; cache: Map<string, number>; id: string; onProgress?: () => void }) {
  const [count, setCount] = createSignal(props.cache.get(props.id) ?? (props.live ? 0 : Array.from(props.text).length))
  let frame = 0
  let previous = 0
  let fractional = 0
  let lastRender = 0
  createEffect(() => {
    const characters = Array.from(props.text)
    const cached = props.cache.get(props.id)
    if (cached === undefined && !props.live) {
      setCount(characters.length)
      return
    }
    if (untrack(count) > characters.length) {
      setCount(characters.length)
      props.cache.set(props.id, characters.length)
    }
    cancelAnimationFrame(frame)
    previous = 0
    const tick = (now: number) => {
      const pending = characters.length - count()
      if (pending <= 0) return
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        setCount(characters.length)
        props.cache.set(props.id, characters.length)
        return
      }
      const elapsed = Math.min(100, previous ? now - previous : 16)
      previous = now
      // More buffered text clears faster; small updates remain visibly smooth.
      fractional += elapsed * Math.min(360, 34 + pending * 0.9) / 1000
      const increment = Math.floor(fractional)
      if (increment && now - lastRender >= 60) {
        fractional -= increment
        lastRender = now
        const next = Math.min(characters.length, count() + increment)
        setCount(next)
        props.cache.set(props.id, next)
        props.onProgress?.()
      }
      if (count() < characters.length) frame = requestAnimationFrame(tick)
    }
    if (untrack(count) < characters.length) frame = requestAnimationFrame(tick)
  })
  onCleanup(() => cancelAnimationFrame(frame))
  return <Show when={count() >= Array.from(props.text).length} fallback={<div class="smooth-message-text" aria-live="off"><Markdown text={Array.from(props.text).slice(0, count()).join("")} /></div>}>
    <Markdown text={props.text} />
  </Show>
}
