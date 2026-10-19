import * as React from "react"

import { useT } from "@/lib/i18n"
import { blocks, reachable, spans, type Block, type Span } from "@/lib/markdown"
import { cn } from "@/lib/utils"

import { Flow } from "./text"

/* Markdown, drawn rather than shown.
 *
 * Two things in the console are written in markdown: a ticket's page, which
 * `/api/tickets/<id>` flattens out of the Notion blocks the runner is handed
 * before a run, and what a session says afterwards — in a comment on the
 * ticket, or in an answer in the workspace's transcript. Left alone both arrive
 * as their own source, and a reader ends up reading the asterisks.
 *
 * What a line is — an item and its number, a table, a bold holding code — is
 * read in `lib/markdown.ts`, without a DOM, where `node --test` checks it. This
 * file only draws it. Every line lands as text, never as markup: React escapes
 * what it is given, and an address is only ever an anchor's child.
 */

/** How deep an item is pushed in. Written out, because Tailwind reads the source. */
const INDENT = ["pl-1", "pl-6", "pl-11", "pl-16"]

/** A column's alignment, by name for the same reason. */
const ALIGN = { left: "text-left", center: "text-center", right: "text-right" }

/** What a line holds, drawn; inside a link's words, nothing is linked again. */
function Spans({ spans, linked = false }: { spans: Span[]; linked?: boolean }) {
  return (
    <>
      {spans.map((span, index) => {
        switch (span.kind) {
          case "code":
            return (
              <code key={index} className="bg-muted rounded px-1 py-0.5 font-mono text-[0.88em]">
                {span.text}
              </code>
            )
          case "strong":
            return (
              <strong key={index} className="font-semibold">
                <Spans spans={span.children} linked={linked} />
              </strong>
            )
          case "em":
            return (
              <em key={index}>
                <Spans spans={span.children} linked={linked} />
              </em>
            )
          case "link":
            return reachable(span.href) && !linked ? (
              <a
                key={index}
                href={span.href}
                target="_blank"
                rel="noreferrer noopener"
                className="text-primary underline underline-offset-2 hover:opacity-80"
              >
                <Spans spans={span.children} linked />
              </a>
            ) : (
              <React.Fragment key={index}>
                <Spans spans={span.children} linked={linked} />
              </React.Fragment>
            )
          default:
            return (
              <React.Fragment key={index}>
                {linked ? span.text : <Flow text={span.text} />}
              </React.Fragment>
            )
        }
      })}
    </>
  )
}

function Inline({ text }: { text: string }) {
  const read = React.useMemo(() => spans(text), [text])
  return <Spans spans={read} />
}

/* A picture drawn where the brief has it, its caption under it, and opened
 * full size in a tab of its own. A picture the board will not hand over is its
 * caption alone — never a broken image, never a link that answers 403. */
function Attached({ block }: { block: Extract<Block, { kind: "attached" }> }) {
  const t = useT()
  const [broken, setBroken] = React.useState(false)
  const source = `/api/files/${block.block}`
  if (block.file === "image" && !broken)
    return (
      <figure className="flex flex-col items-start gap-1">
        <a href={source} target="_blank" rel="noreferrer noopener" title={t("Open full size")}>
          <img
            src={source}
            alt={block.label || t("Image attached to the ticket")}
            loading="lazy"
            onError={() => setBroken(true)}
            className="max-h-96 max-w-full cursor-zoom-in rounded-lg border object-contain"
          />
        </a>
        {block.label ? (
          <figcaption className="text-muted-foreground text-xs">{block.label}</figcaption>
        ) : null}
      </figure>
    )
  const label =
    block.label ||
    (block.file === "image" ? t("Image attached to the ticket") : t("File attached to the ticket"))
  if (broken) return <p className="text-muted-foreground">{label}</p>
  return (
    <p>
      <a
        href={source}
        target="_blank"
        rel="noreferrer noopener"
        className="text-primary underline underline-offset-2 hover:opacity-80"
      >
        📎 {label}
      </a>
    </p>
  )
}

/** `className` sets the size of the text, which headings follow. */
export function Markdown({ text, className }: { text: string; className?: string }) {
  const drawn = React.useMemo(() => blocks(text), [text])
  if (!drawn.length) return null
  return (
    <div className={cn("flex flex-col gap-2", className ?? "text-sm leading-relaxed")}>
      {drawn.map((block, index) => {
        switch (block.kind) {
          case "heading": {
            const Tag = block.level === 1 ? "h3" : block.level === 2 ? "h4" : "h5"
            return (
              <Tag
                key={index}
                className={cn(
                  // A heading opening a bubble is not pushed off its own top;
                  // its size is the text's, wherever that was set.
                  "first:mt-0",
                  block.level === 1
                    ? "mt-4 text-[1.15em] font-semibold"
                    : "mt-3 text-[1em] font-semibold"
                )}
              >
                <Inline text={block.text} />
              </Tag>
            )
          }
          case "item":
            return (
              <div key={index} className={cn("flex gap-2", INDENT[block.depth])}>
                <span className="text-muted-foreground min-w-4 shrink-0 text-center tabular-nums">
                  {block.marker}
                </span>
                <span className={block.done ? "text-muted-foreground line-through" : ""}>
                  <Inline text={block.text} />
                </span>
              </div>
            )
          case "quote":
            return (
              <blockquote
                key={index}
                className="border-tr-violet/50 text-muted-foreground border-l-2 pl-3"
              >
                <Inline text={block.text} />
              </blockquote>
            )
          case "code":
            return (
              <pre
                key={index}
                className="scroll-thin bg-muted/60 overflow-x-auto rounded-lg border px-3 py-2 font-mono text-xs leading-relaxed"
              >
                {block.lines.join("\n")}
              </pre>
            )
          case "table": {
            // Wider than a bubble on a phone, it scrolls on its own rather
            // than pushing the bubble out.
            const align = (column: number) => ALIGN[block.align[column] ?? "left"]
            return (
              <div key={index} className="scroll-thin overflow-x-auto rounded-lg border">
                <table className="w-full border-collapse text-xs">
                  <thead className="bg-muted/60">
                    <tr>
                      {block.head.map((cell, column) => (
                        <th
                          key={column}
                          className={cn(
                            "border-b px-3 py-1.5 font-semibold whitespace-nowrap",
                            align(column)
                          )}
                        >
                          <Inline text={cell} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, line) => (
                      <tr key={line} className="border-b last:border-b-0">
                        {row.map((cell, column) => (
                          <td
                            key={column}
                            className={cn("min-w-28 px-3 py-1.5 align-top", align(column))}
                          >
                            <Inline text={cell} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          }
          case "rule":
            // Tailwind's reset leaves every border at zero width, so a bare
            // `<hr>` is a blank line rather than a rule: the break has to be
            // asked for by name.
            return <hr key={index} className="border-border my-3 border-t" />
          case "attached":
            return <Attached key={index} block={block} />
          default:
            return (
              <p key={index} className="whitespace-pre-wrap">
                <Inline text={block.text} />
              </p>
            )
        }
      })}
    </div>
  )
}
