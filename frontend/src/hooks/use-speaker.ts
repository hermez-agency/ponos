import * as React from "react"

import { api } from "@/lib/api"

/* The voice of the page: sentences in, sound out, one after the other.
 *
 * Played through the Web Audio API and not an `<audio>` element: a sentence is
 * a WAV the server made, decoded in memory, with no address for the page's
 * Content-Security-Policy to allow, and the next one can be fetched and decoded
 * while this one plays — which is what keeps the silence between two sentences
 * short, and the first sound near the end of the first request.
 *
 * iOS and Safari keep an `AudioContext` suspended until a gesture resumes it,
 * and a context made later is suspended again. `unlock` is therefore called
 * from the tap that starts the voice mode or a Listen button, never from an
 * effect: it makes (or resumes) the context and plays a silent frame, which is
 * what the browser counts as the page having been allowed to make a sound.
 *
 * `stop` is a generation: whatever was being fetched for the previous one is
 * dropped when it arrives rather than played over the new one.
 */

interface Queued {
  sound: Promise<AudioBuffer | null>
}

export function useSpeaker({ onError }: { onError: (error: unknown) => void }) {
  const [speaking, setSpeaking] = React.useState(false)
  const context = React.useRef<AudioContext | null>(null)
  const generation = React.useRef(0)
  const queue = React.useRef<Queued[]>([])
  const playing = React.useRef<{ source: AudioBufferSourceNode; done: () => void } | null>(null)
  const running = React.useRef(false)
  const failed = React.useRef(onError)
  failed.current = onError

  const unlock = React.useCallback(() => {
    const Context =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Context) return
    if (!context.current) context.current = new Context()
    const audio = context.current
    if (audio.state === "suspended") void audio.resume().catch(() => {})
    const silence = audio.createBufferSource()
    silence.buffer = audio.createBuffer(1, 1, 22050)
    silence.connect(audio.destination)
    silence.start(0)
  }, [])

  const run = React.useCallback(async () => {
    if (running.current) return
    running.current = true
    setSpeaking(true)
    const mine = generation.current
    try {
      while (queue.current.length && generation.current === mine) {
        const next = queue.current.shift()!
        const buffer = await next.sound
        const audio = context.current
        if (!buffer || !audio || generation.current !== mine) continue
        await new Promise<void>((done) => {
          const source = audio.createBufferSource()
          source.buffer = buffer
          source.connect(audio.destination)
          source.onended = () => done()
          playing.current = { source, done }
          source.start(0)
        })
        playing.current = null
      }
    } finally {
      running.current = false
      // A stop and a say in the same tick: the new generation runs its own loop.
      if (generation.current === mine) setSpeaking(false)
      else if (queue.current.length) void run()
    }
  }, [])

  /** Fetches and decodes now, plays in turn. */
  const say = React.useCallback(
    (sentence: string, language: string) => {
      const mine = generation.current
      const sound = (async () => {
        try {
          const audio = context.current
          if (!audio) return null
          const bytes = await api.speak(sentence, language)
          if (generation.current !== mine) return null
          return await audio.decodeAudioData(bytes)
        } catch (error) {
          if (generation.current === mine) {
            generation.current += 1
            queue.current = []
            failed.current(error)
          }
          return null
        }
      })()
      queue.current.push({ sound })
      void run()
    },
    [run]
  )

  const stop = React.useCallback(() => {
    generation.current += 1
    queue.current = []
    const current = playing.current
    playing.current = null
    if (current) {
      current.source.onended = null
      try {
        current.source.stop()
      } catch {
        // Already over.
      }
      current.done()
    }
    setSpeaking(false)
  }, [])

  React.useEffect(
    () => () => {
      stop()
      void context.current?.close().catch(() => {})
      context.current = null
    },
    [stop]
  )

  return { speaking, unlock, say, stop }
}
