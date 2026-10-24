# Telegram and Slack

[The guide](README.md) · [Ponos](../README.md)

Being told, and answering from your phone.

## Being told, and answering with one word

A desktop notification names its ticket, and clicking it opens that ticket's Notion page
— the notification is where you act from, not a title you then go and look for on the
board. It is not the comment: the title says what happened and on which project (*Ponos has a question — Leadz*,
*Ticket done — Adam*), the body gives the ticket's name and one sentence, and a **See the PR** button comes with
a pull request. A ticket has one notification, replaced as it moves on rather than stacked, and its icon, the logo, is
drawn on a transparent background, in the icon theme too so the dock shows the same one. But it only works if you are in front of that desktop, and the two moments that
need you are exactly the two you are least likely to be there for: the agent
asked a question, and a pull request is waiting. So the runner can also write to
**Telegram** or **Slack** — and this is the half that matters: **what you answer there
lands on the ticket.**

```
   the runner                  your phone                   the ticket

   blocked ────────▶  🙋 Stuck · Le header
                      The ticket names two headers.
                      Which one goes?
                      1. The dashboard's · 2. The public site's
                      notion.so/…
                                   │
                                   │  “2”
                                   ▼
                      ✓ noted on “Le header”  ──────▶  a comment on the page
                                                       │
   next run  ◀──────────────────────────────────────────┘  the ticket runs again
```

Nothing new on the board, and no second mechanism: the reply becomes a **Notion comment**,
and a comment is already what wakes a blocked ticket (see
[The discussion on a ticket](tickets.md#the-discussion-on-a-ticket)). A *oui* typed on a phone
travels the exact path a *oui* typed into Notion does — same waking rules, same prompt.

That comment is posted with the runner's own token, and it is still **yours**: it opens
with *Answered from Telegram by …*, which is what tells the next run that this is the
ticket's author speaking and not the runner's own last word. Without that reading, a *oui*
from a phone would close the very question it answers — see
[Talking to it in the comments](tickets.md#talking-to-it-in-the-comments), where the runner does
write in the comments in its own name.

*yes*, *oui*, *ok*, *go*, 👍 — and their opposites — are read as a verdict and spelled out
for the session that will read them, because a bare "oui" means nothing to an agent that
never saw the notification. Anything else travels verbatim; a word plus a sentence keeps
both.

| Read as a yes | Read as a no |
| --- | --- |
| *yes*, *oui*, *ok*, *go*, *ship it*, *vas-y*, *ça marche*, 👍, ✅ … | *no*, *non*, *stop*, *cancel*, *laisse tomber*, *annule*, 👎, ❌ … |

The full lists are `_YES` and `_NO` in `src/ponos/channels/__init__.py`.

Answers are read **at the top of each run**, so a ticket answered thirty seconds ago is
picked up by that very run. Which question an answer belongs to is settled in three steps,
narrowest first: a reply *to* the runner's message (a Telegram reply, a Slack thread), then
a ticket named in the text — its link, or the eight characters the runner prints
everywhere — and failing both, the last question asked, which is what "oui" means when it
arrives thirty seconds after the phone buzzed.

That third step is the one a **shared room does not get**: in Slack the message beside
yours belongs to somebody else's conversation, so an answer there has to be in the thread
of the question, or name its ticket. And the *first* poll of a channel only establishes
where "now" is — Telegram keeps a day of updates and Slack a channel's whole history, and
none of that was addressed to a runner that was not listening yet.

### Telegram — the two-minute channel

No public URL, no webhook, no domain: the runner *polls*, which is what makes this the one
channel that installs on a laptop behind a NAT.

1. talk to [@BotFather](https://t.me/BotFather) → `/newbot` → put the token in
   `secrets.env` as `PONOS_TELEGRAM_TOKEN` (or type it in the console's Settings);
2. open the chat with your new bot and say anything to it;
3. `ponos notify --pair` — it reads that message and writes the chat id into your
   configuration. (The usual advice is to paste your token into somebody else's bot, which
   is the same as handing them the channel.)
4. `ponos notify` sends you a first message.

Only that chat is ever read. A bot token is a public address — anyone who guesses the
bot's name can write to it — so a message from any other chat is dropped before it can
become a comment on your board. In a **group**, though, everybody in it writes in that
chat: name who may answer with their Telegram user ids —

```toml
[notify.telegram]
allowed_users = [123456789]
```

— and everybody else's messages are read past. Empty is the old behaviour, and it is
fine in a private chat, where only you write; see
[who can write a ticket](server.md#who-can-write-a-ticket-can-run-commands-on-that-machine) for
why it is not in a group.

### Slack — where the team already is

A question is posted to the channel and answered **in its thread**, which is how two
tickets can be waiting at once without their answers being confused — and why a message
typed in the channel itself answers nothing unless it names its ticket. A room has other
conversations in it, and a colleague's "ok" is not an approval of anything.

1. [api.slack.com/apps](https://api.slack.com/apps) → *Create New App* → *From scratch*;
2. *OAuth & Permissions* → Bot Token Scopes: `chat:write`, and the history scope matching
   where you put it — `channels:history` for a public channel, `groups:history` for a
   private one, `im:history` for a direct message;
3. *Install to Workspace*, copy the `xoxb-` token into `secrets.env` as `PONOS_SLACK_TOKEN`;
4. `/invite @your-bot` in the channel — the step everyone forgets — and put the channel ID
   (`···` → *View channel details*, at the bottom) in `channel`.
5. `allowed_users = ["U0123ABCD"]` — the member ids of the people whose answers count
   (profile → `···` → *Copy member ID*). Empty, anybody in the channel can answer, and
   `ponos doctor` says so.

### Telegram or Slack

| | Telegram | Slack |
| --- | --- | --- |
| Best for | one person, on the move | a team that already lives in a channel |
| Setup | a bot token and one message | an app, two scopes, an invitation |
| Public URL needed | no — the runner polls | no — the runner polls |
| Where you answer | a reply, the ticket's link, or just the next message | in the question's thread, or naming the ticket |
| Who is read | the paired chat, and nobody else | the configured channel |

### What gets sent, and what does not

```toml
[notify]
replies = true                             # read what you write back
events = ["blocked", "failed", "done"]     # the moments worth a message
```

`blocked` is the one that expects something back; `done` is the pull request waiting for
you; `failed` is a log to read. Drop what you do not want woken for — `events = ["blocked"]`
is a defensible whole configuration. `replies = false` keeps the messages and stops the
listening.

Everything here fails quietly, like desktop notifications: a token that expired, a channel
the bot was removed from, a network that is down. None of it is a reason for a ticket to
fail, and the Notion comment stays the record either way. `ponos doctor` says which
channel is live, as whom, and where.

**Why not WhatsApp.** Its API delivers inbound messages only to a public HTTPS webhook you
host and have verified by Meta, on a business account — a server, in other words, which is
the opposite of a runner living on your machine. Outbound alone would be a notification you
cannot answer, which is the half that matters least. A channel is four methods
(`src/ponos/channels/`), so the day you have that endpoint it is one file.
