import * as React from "react"
import { CopyIcon, Trash2, UserPlus } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { api, why } from "@/lib/api"
import { copy } from "@/lib/copy"
import { Worded, useT } from "@/lib/i18n"
import type { Role } from "@/lib/role"
import { settingsFrench } from "@/lib/settings-store"
import type { Account, Invitation } from "@/lib/types"

import { ConfirmDialog } from "./confirm-dialog"
import { when } from "./ticket-bits"

/* The settings' Accounts page: who the console is shared with, and as what.
 *
 * Ponos sends no email: an invitation is a link drawn here, for one role,
 * copied, and given however you like — shown once, since the server keeps
 * only its digest (`web/accounts.py`). The console's own sign-in heads the
 * list and is the first admin whatever is chosen here: it has no role to
 * change and no trash, so nobody invited can take the console from whoever
 * installed it.
 */

const ROLES: { role: Role; label: string; can: string }[] = [
  { role: "reader", label: "Reader", can: "sees the board, the tickets and the projects, and changes nothing" },
  { role: "member", label: "Member", can: "writes, launches, answers and validates tickets" },
  { role: "admin", label: "Admin", can: "also changes the settings, the vault, the forced validation and the accounts" },
]

const labelOf = (role: string) => ROLES.find((one) => one.role === role)?.label ?? role

function RolePicker({
  value,
  onChange,
  label,
  disabled,
}: {
  value: Role
  onChange: (role: Role) => void
  label: string
  disabled?: boolean
}) {
  const t = useT()
  return (
    <Select value={value} onValueChange={(next) => onChange(next as Role)} disabled={disabled}>
      <SelectTrigger size="sm" aria-label={label} className="w-36" data-slot="account-role">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {ROLES.map((one) => (
          <SelectItem key={one.role} value={one.role}>
            {t(one.label)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function Invite({ onDrawn }: { onDrawn: () => void }) {
  const t = useT()
  const [role, setRole] = React.useState<Role>("member")
  const [link, setLink] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const draw = async () => {
    setBusy(true)
    try {
      const drawn = await api.invite(role)
      setLink(drawn.link)
      onDrawn()
    } catch (error) {
      toast.error(t("The invitation could not be drawn"), { description: why(error) })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card data-card="invite" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-3 sm:px-6">
        <CardTitle className="text-base">{t("Invite somebody")}</CardTitle>
        <CardDescription className="text-[13px]">
          {t(
            "Ponos sends no email: copy the link and give it yourself. It makes one account, within a week."
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 px-5 pb-5 sm:px-6">
        <ul className="text-muted-foreground flex flex-col gap-0.5 text-[13px]">
          {ROLES.map((one) => (
            <li key={one.role}>
              <span className="text-foreground font-medium">{t(one.label)}</span> — {t(one.can)}
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap items-center gap-2">
          <RolePicker value={role} onChange={setRole} label={t("Role of the invitation")} />
          <Button size="sm" onClick={() => void draw()} disabled={busy} data-slot="invite-draw">
            <UserPlus />
            {t("Draw a link")}
          </Button>
        </div>
        {link ? (
          <div className="bg-muted flex items-start gap-2 rounded-md border py-1 pr-1 pl-3">
            <code className="min-w-0 flex-1 py-1.5 font-mono text-xs break-all" data-slot="invite-link">
              {link}
            </code>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={() => void copy(link, t("the invitation"))}
              aria-label={t("Copy the link")}
            >
              <CopyIcon />
            </Button>
          </div>
        ) : null}
        {link ? (
          <p className="text-muted-foreground text-[13px]">
            {t("Shown once: the console keeps only what checks it.")}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function AccountRow({ account, onChanged }: { account: Account; onChanged: () => void }) {
  const t = useT()
  const [busy, setBusy] = React.useState(false)
  const change = async (role: Role) => {
    setBusy(true)
    try {
      await api.setRole(account.id, role)
      toast.success(t("{{name}} is now {{role}}", { name: account.name, role: t(labelOf(role)).toLowerCase() }))
      onChanged()
    } catch (error) {
      toast.error(t("The role could not be changed"), { description: why(error) })
    } finally {
      setBusy(false)
    }
  }
  const remove = async () => {
    try {
      await api.deleteAccount(account.id)
    } catch (error) {
      toast.error(t("The account could not be deleted"), { description: why(error) })
      return false
    }
    toast.success(t("{{name}} has no account any more", { name: account.name }))
    onChanged()
  }
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3" data-account={account.email}>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{account.name}</p>
        <p className="text-muted-foreground truncate text-xs">{account.email}</p>
      </div>
      {account.owner ? (
        <Badge variant="secondary" title={t("The console's own sign-in, in its configuration: the first admin.")}>
          {t("Admin")} · {t("this console's sign-in")}
        </Badge>
      ) : (
        <>
          <RolePicker
            value={account.role}
            onChange={(role) => void change(role)}
            label={t("Role of {{name}}", { name: account.name })}
            disabled={busy}
          />
          <ConfirmDialog
            destructive
            title={t("Delete the account of {{name}}?", { name: account.name })}
            description={t(
              "Every browser signed in as {{name}} is signed out at once. What they did stays in the tickets' history, under their name.",
              { name: account.name }
            )}
            confirm={t("Delete the account")}
            onConfirm={remove}
            trigger={
              <Button variant="ghost" size="icon-sm" aria-label={t("Delete the account of {{name}}", { name: account.name })}>
                <Trash2 />
              </Button>
            }
          />
        </>
      )}
    </li>
  )
}

function InvitationRow({ invitation, onChanged }: { invitation: Invitation; onChanged: () => void }) {
  const t = useT()
  const withdraw = async () => {
    try {
      await api.withdrawInvitation(invitation.id)
      onChanged()
    } catch (error) {
      toast.error(t("The invitation could not be withdrawn"), { description: why(error) })
    }
  }
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3" data-invitation={invitation.id}>
      <div className="min-w-0 flex-1">
        <p className="text-sm">{t("A link for a {{role}}", { role: t(labelOf(invitation.role)).toLowerCase() })}</p>
        <p className="text-muted-foreground text-xs">
          {t("drawn {{when}}, good until {{until}}", { when: when(invitation.created), until: when(invitation.expires) })}
          {invitation.by ? ` · ${invitation.by}` : ""}
        </p>
      </div>
      <Button variant="ghost" size="sm" onClick={() => void withdraw()}>
        {t("Withdraw")}
      </Button>
    </li>
  )
}

function Accounts() {
  const t = useT()
  const [listed, setListed] = React.useState<{ accounts: Account[]; invitations: Invitation[] } | null>(null)
  const [problem, setProblem] = React.useState("")
  const read = React.useCallback(() => {
    api.accounts().then(
      (fresh) => {
        setListed(fresh)
        setProblem("")
      },
      (error: unknown) => setProblem(why(error))
    )
  }, [])
  React.useEffect(() => read(), [read])
  return (
    <div className="flex flex-col gap-4" data-slot="accounts-page">
      <Invite onDrawn={read} />
      <Card className="gap-0 py-0">
        <CardHeader className="gap-1 px-5 pt-5 pb-1 sm:px-6">
          <CardTitle className="text-base">{t("Who has an account")}</CardTitle>
          <CardDescription className="text-[13px]">
            {t("What each of them writes on a ticket from the console is signed with their name.")}
          </CardDescription>
        </CardHeader>
        <CardContent className="px-5 pb-3 sm:px-6">
          {problem ? <p className="text-destructive py-3 text-sm">{problem}</p> : null}
          <ul className="divide-y">
            {listed?.accounts.map((account) => (
              <AccountRow key={account.id} account={account} onChanged={read} />
            ))}
          </ul>
          {listed && !listed.accounts.some((account) => !account.owner) ? (
            <p className="text-muted-foreground py-3 text-sm">{t("Nobody else has an account yet.")}</p>
          ) : null}
          {listed?.invitations.length ? (
            <>
              <h4 className="mt-3 text-sm font-semibold">{t("Links not taken yet")}</h4>
              <ul className="divide-y">
                {listed.invitations.map((invitation) => (
                  <InvitationRow key={invitation.id} invitation={invitation} onChanged={read} />
                ))}
              </ul>
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

export function AccountsPage() {
  return (
    <Worded words={settingsFrench}>
      <Accounts />
    </Worded>
  )
}
