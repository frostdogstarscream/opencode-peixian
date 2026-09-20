let pending: Promise<unknown> = Promise.resolve()

export function queueDiagram(render: () => Promise<void>) {
  pending = pending.then(render, render)
}
