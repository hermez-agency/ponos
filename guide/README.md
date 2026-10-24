# The Ponos guide

[Ponos](../README.md) · [Contributing](../CONTRIBUTING.md)

How to install Ponos, configure it and use it, one page per subject. Working on Ponos itself
— the architecture, the console's code, the tests, the mascot, releases — is in
[CONTRIBUTING.md](../CONTRIBUTING.md).

## [Installing Ponos](installation.md)

- [Installation](installation.md#installation)
- [Uninstall](installation.md#uninstall)

## [Configuring Ponos](configuration.md)

- [Configuration](configuration.md#configuration)
  - [1. Create a Notion integration](configuration.md#1-create-a-notion-integration)
  - [2. Share one page with it](configuration.md#2-share-one-page-with-it)
  - [3. Let the runner build the rest](configuration.md#3-let-the-runner-build-the-rest)
  - [The step everyone forgets](configuration.md#the-step-everyone-forgets)
  - [4. The rest of the file](configuration.md#4-the-rest-of-the-file)
  - [Who answers the sessions](configuration.md#who-answers-the-sessions)
  - [Every other model](configuration.md#every-other-model)
  - [Connect GitHub in one click](configuration.md#connect-github-in-one-click)
  - [Or an access token](configuration.md#or-an-access-token)
  - [Several GitHub accounts](configuration.md#several-github-accounts)
  - [Keys a ticket may use: the vault](configuration.md#keys-a-ticket-may-use-the-vault)

## [The board](board.md)

- [Without Notion: the board as Markdown files](board.md#without-notion-the-board-as-markdown-files)
  - [Both, and what happens when they disagree](board.md#both-and-what-happens-when-they-disagree)
- [The Notion side](board.md#the-notion-side)
  - [The tickets database](board.md#the-tickets-database)
  - [The type of a ticket](board.md#the-type-of-a-ticket)
  - [The sub-type of a code ticket](board.md#the-sub-type-of-a-code-ticket)
  - [The model of a ticket](board.md#the-model-of-a-ticket)
  - [Following the work](board.md#following-the-work)
  - [The projects database](board.md#the-projects-database)
  - [The context page — who the work is for](board.md#the-context-page--who-the-work-is-for)
  - [The agents database — who handles the ticket](board.md#the-agents-database--who-handles-the-ticket)
  - [The goals database — what the ticket is for](board.md#the-goals-database--what-the-ticket-is-for)

## [A ticket's life](tickets.md)

- [The discussion on a ticket](tickets.md#the-discussion-on-a-ticket)
- [Talking to it in the comments](tickets.md#talking-to-it-in-the-comments)
- [Looking again at what is blocked](tickets.md#looking-again-at-what-is-blocked)
- [A prompt on every change of status](tickets.md#a-prompt-on-every-change-of-status)
- [The statuses](tickets.md#the-statuses)
- [Merging is the only gesture](tickets.md#merging-is-the-only-gesture)
- [Ten tickets on one repository](tickets.md#ten-tickets-on-one-repository)
- [Validated, and what it sets off](tickets.md#validated-and-what-it-sets-off)
- [Force validated: skipping the review](tickets.md#force-validated-skipping-the-review)
- [What comes back on its own](tickets.md#what-comes-back-on-its-own)

## [Telegram and Slack](channels.md)

- [Being told, and answering with one word](channels.md#being-told-and-answering-with-one-word)
  - [Telegram — the two-minute channel](channels.md#telegram--the-two-minute-channel)
  - [Slack — where the team already is](channels.md#slack--where-the-team-already-is)
  - [Telegram or Slack](channels.md#telegram-or-slack)
  - [What gets sent, and what does not](channels.md#what-gets-sent-and-what-does-not)

## [The console](console.md)

- [The web console](console.md#the-web-console)
  - [Goals](console.md#goals)
  - [Ideas](console.md#ideas)
  - [Keeping it running](console.md#keeping-it-running)
  - [What is behind that port](console.md#what-is-behind-that-port)
  - [The first connection](console.md#the-first-connection)
  - [Signing in instead of pasting a token](console.md#signing-in-instead-of-pasting-a-token)
- [Connect Ponos to Claude](console.md#connect-ponos-to-claude)
  - [What Claude can do with it](console.md#what-claude-can-do-with-it)
  - [How the connection works](console.md#how-the-connection-works)

## [Every command](usage.md)

- [Usage](usage.md#usage)
  - [Exit codes](usage.md#exit-codes)
  - [What `clean` removes, and what it refuses to](usage.md#what-clean-removes-and-what-it-refuses-to)

## [Safety](safety.md)

- [What protects your code](safety.md#what-protects-your-code)

## [Credits and limits](credits.md)

- [When the credits run out](credits.md#when-the-credits-run-out)
  - [What a session may do alone](credits.md#what-a-session-may-do-alone)
  - [Stopping before the wall](credits.md#stopping-before-the-wall)
  - [Spending limits](credits.md#spending-limits)

## [Servers and containers](server.md)

- [On a server](server.md#on-a-server)
  - [Who can write a ticket can run commands on that machine](server.md#who-can-write-a-ticket-can-run-commands-on-that-machine)
- [Docker](server.md#docker)
- [Install with Dokploy](server.md#install-with-dokploy)
  - [From this repository instead](server.md#from-this-repository-instead)

## [Troubleshooting](troubleshooting.md)

- [While installing](troubleshooting.md#while-installing)
- [When it does not work](troubleshooting.md#when-it-does-not-work)
