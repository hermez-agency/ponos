import * as React from "react"
import { toast } from "sonner"

import { useRecorder } from "@/hooks/use-recorder"
import { api, why } from "@/lib/api"
import { currentLanguage, useT } from "@/lib/i18n"
import {
  advance,
  finished,
  interruption,
  interrupts,
  mayHaveGrown,
  opened,
  unsaid,
  wordsOf,
  type Gate,
  type Mode,
} from "@/lib/voice-mode"

import type { useSpeaker } from "./use-speaker"

/* The conversation without the keyboard: listen, answer, listen again.
 *
 *   listening  the microphone records; a silence after speech ends the sentence
 *   thinking   it is transcribed and sent, and Ponos works on the answer
 *   speaking   the answer is read sentence by sentence as it streams in, and
 *              the microphone is open again to hear somebody talk over it
 *
 * The recorder is the dictation's (`use-recorder`), and so is the level it
 * draws: the end of a sentence is read off the same peaks as the meter. What
 * is said of a reply is decided by the server (`speech.plan`), which is asked
 * again as the text grows and answers the same first sentences each time, so
 * that "sentences already spoken" is a count and nothing more.
 *
 * A reply is never recorded over its own voice: when it has been read to the
 * end, the recording is thrown away and a new one begun. Only a barge-in keeps
 * the recording going, since what was said is the start of the next sentence.
 */

type Speaker = ReturnType<typeof useSpeaker>

interface Message {
  role: string
  parts: ReadonlyArray<{ type: string; content?: unknown }>
}

/** The turn being answered: where it began in the conversation, and how far it was read. */
interface Reply {
  since: number
  spoken: number
  sawBusy: boolean
  asked: string
  asking: boolean
  closed: boolean
  later: { text: string; final: boolean } | null
}

export function useVoiceMode({
  ready,
  reason,
  speaker,
  transcribe,
  send,
  messages,
  busy,
}: {
  ready: boolean
  /** Why the server cannot speak or transcribe, when it cannot. */
  reason: string
  speaker: Speaker
  transcribe: (audio: Blob) => Promise<string>
  send: (text: string) => Promise<boolean>
  messages: ReadonlyArray<Message>
  busy: boolean
}) {
  const t = useT()
  const recorder = useRecorder()
  const [mode, setMode] = React.useState<Mode>("off")
  const [done, setDone] = React.useState(false)
  const [turn, setTurn] = React.useState<number | null>(null)
  const current = React.useRef<Mode>("off")
  const reply = React.useRef<Reply | null>(null)
  const gate = React.useRef<Gate>(opened())
  const barge = React.useRef(0)
  const sampled = React.useRef(0)
  const ending = React.useRef(false)

  const go = React.useCallback((next: Mode) => {
    current.current = next
    setMode(next)
  }, [])

  const blocked = !ready
    ? t(reason || "The voice is not available")
    : recorder.access === "unsupported"
      ? t("This browser gives the page no microphone")
      : recorder.access === "denied"
        ? t("The microphone is blocked for this page — allow it in the browser's site settings")
        : ""

  const abandon = React.useCallback(() => {
    reply.current = null
    setTurn(null)
    setDone(false)
  }, [])

  const leave = React.useCallback(() => {
    speaker.stop()
    recorder.cancel()
    abandon()
    go("off")
  }, [speaker, recorder, abandon, go])

  /** Back to listening, from a microphone that heard nothing of the voice. */
  const listen = React.useCallback(async () => {
    abandon()
    await recorder.stop()
    if (current.current === "off") return
    gate.current = opened()
    barge.current = 0
    go("listening")
    try {
      await recorder.start()
    } catch (error) {
      toast.error(t("The microphone could not be opened"), { description: why(error) })
      leave()
    }
  }, [abandon, recorder, go, leave, t])

  const begin = React.useCallback(async () => {
    // From the tap itself: after an await, iOS no longer takes it for one.
    speaker.stop()
    speaker.unlock()
    // Loads the voice while the first sentence is being said and written.
    void api.speakPlan("", currentLanguage(), false).catch(() => {})
    gate.current = opened()
    barge.current = 0
    go("listening")
    try {
      await recorder.start()
    } catch (error) {
      toast.error(t("The microphone could not be opened"), { description: why(error) })
      go("off")
    }
  }, [speaker, recorder, go, t])

  const toggle = React.useCallback(() => {
    if (current.current === "off") {
      if (!blocked) void begin()
    } else leave()
  }, [begin, blocked, leave])

  /** The sentence is over: transcribe it, say it, and wait for the answer. */
  const finish = React.useCallback(async () => {
    if (ending.current) return
    ending.current = true
    try {
      const audio = await recorder.stop()
      if (current.current !== "listening") return
      go("thinking")
      let said = ""
      try {
        said = audio ? (await transcribe(audio)).trim() : ""
      } catch (error) {
        toast.error(t("The recording could not be transcribed"), { description: why(error) })
      }
      if ((current.current as Mode) !== "thinking") return
      if (!said) return await listen()
      reply.current = { since: messages.length, spoken: 0, sawBusy: false, asked: "", asking: false, closed: false, later: null }
      setDone(false)
      setTurn(messages.length)
      if (!(await send(said))) await listen()
    } finally {
      ending.current = false
    }
  }, [recorder, go, transcribe, t, listen, messages.length, send])

  /** Somebody talks over the voice, or presses Interrupt. */
  const interrupt = React.useCallback(
    (keepRecording: boolean) => {
      speaker.stop()
      if (!keepRecording) return void listen()
      abandon()
      // What was said so far is the start of the sentence.
      gate.current = { loud: 1000, quiet: 0, elapsed: 0, heard: true }
      barge.current = 0
      go("listening")
    },
    [speaker, listen, abandon, go]
  )

  // The answer: what the assistant said since this turn began.
  const last = turn === null ? undefined : messages[messages.length - 1]
  const words = turn !== null && messages.length > turn + 1 && last?.role === "assistant" ? wordsOf(last.parts) : ""

  /** Asks the server which sentences of the answer so far are worth saying, and says the new ones. */
  const pump = async (text: string, final: boolean) => {
    const mine = reply.current
    if (!mine || mine.closed) return
    if (mine.asking) {
      mine.later = { text, final }
      return
    }
    mine.asking = true
    try {
      let next: { text: string; final: boolean } | null = { text, final }
      while (next && reply.current === mine) {
        mine.later = null
        mine.asked = next.text
        mine.closed = next.final
        const plan = await api.speakPlan(next.text, currentLanguage(), next.final)
        if (reply.current !== mine) return
        for (const sentence of unsaid(plan.sentences, mine.spoken)) {
          speaker.say(sentence, plan.language)
          mine.spoken += 1
        }
        if (next.final) setDone(true)
        next = mine.later
      }
    } catch (error) {
      if (reply.current === mine) {
        toast.error(t("The answer could not be read aloud"), { description: why(error) })
        void listen()
      }
    } finally {
      mine.asking = false
    }
  }

  // Everything below runs on every render with the latest of these, so that no
  // effect has to name a function that changes with each microphone sample.
  const latest = React.useRef({ finish, interrupt, pump, listen, leave, go, recorder })
  latest.current = { finish, interrupt, pump, listen, leave, go, recorder }

  // The end of a sentence, and a voice over the voice, from the microphone's level.
  React.useEffect(() => {
    if (recorder.state !== "recording") return
    const now = performance.now()
    const ms = Math.min(now - (sampled.current || now), 500)
    sampled.current = now
    const level = recorder.levels[recorder.levels.length - 1] ?? 0
    if (current.current === "listening") {
      gate.current = advance(gate.current, level, ms)
      if (finished(gate.current)) void latest.current.finish()
    } else if (current.current === "speaking") {
      barge.current = interruption(barge.current, level, ms)
      if (interrupts(barge.current)) latest.current.interrupt(true)
    }
  }, [recorder.levels, recorder.state])

  React.useEffect(() => {
    const mine = reply.current
    if (!mine || mine.closed || (mode !== "thinking" && mode !== "speaking")) return
    if (busy) mine.sawBusy = true
    const final = mine.sawBusy && !busy
    if (final || mayHaveGrown(mine.asked, words)) void latest.current.pump(words, final)
  }, [words, busy, mode])

  // The first sentence is heard: the microphone opens again for a barge-in.
  React.useEffect(() => {
    if (!speaker.speaking || current.current !== "thinking" || !reply.current) return
    latest.current.go("speaking")
    barge.current = 0
    sampled.current = 0
    void latest.current.recorder.start().catch(() => {})
  }, [speaker.speaking, mode])

  // Read to the end: listen again.
  React.useEffect(() => {
    if (done && !speaker.speaking && (mode === "thinking" || mode === "speaking")) void latest.current.listen()
  }, [done, speaker.speaking, mode])

  // The voice stops being available: no microphone left open.
  React.useEffect(() => {
    if (!ready && current.current !== "off") latest.current.leave()
  }, [ready])

  return {
    mode,
    blocked,
    levels: recorder.levels,
    seconds: recorder.seconds,
    toggle,
    leave,
    interrupt: () => interrupt(false),
  }
}
