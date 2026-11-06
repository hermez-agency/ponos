import * as React from "react";
import { Globe, RotateCcw, X } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, why } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { BrowserLive, ProjectSettings } from "@/lib/types";

import { ConfirmDialog } from "./confirm-dialog";

/* Ponos's browser, for one project: which browser its external tickets act in,
 * the sites its profile is signed in to, a reset, and the live view.
 *
 * The live view is a screenshot the browser writes and the page fetches again
 * every second — no stream to keep open, nothing a proxy could cut — and a
 * click on it is a click in the browser, at the same place. It is how a
 * person finishes a sign-in a second factor stopped: « Sign in here » opens
 * a browser of the console's own on the project's profile, at the site's
 * address; the person clicks, types the code, closes it, and what it signed in
 * to stays for the ticket that resumes.
 */

const LOOK_EVERY = 1000;
const SELECT =
  "border-input bg-background h-9 rounded-md border px-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50";

export function BrowserCard({
  browser,
  saving,
  onSave,
  onChanged,
}: {
  browser: ProjectSettings["browser"];
  saving: boolean;
  onSave: (value: "ponos" | "chrome") => Promise<void>;
  onChanged: () => void;
}) {
  const t = useT();
  const [running, setRunning] = React.useState<BrowserLive[]>([]);
  const [address, setAddress] = React.useState("");
  const [opening, setOpening] = React.useState(false);
  const name = browser.project;

  // The browsers of this project running now: a session's, or one opened here.
  React.useEffect(() => {
    if (!name) return;
    let gone = false;
    const look = () =>
      api.browser().then(
        (read) =>
          !gone &&
          setRunning(read.live.filter((item) => item.project === name)),
        () => undefined,
      );
    void look();
    const timer = window.setInterval(look, 3000);
    return () => {
      gone = true;
      window.clearInterval(timer);
    };
  }, [name]);

  const reset = async () => {
    try {
      await api.resetBrowser(name);
    } catch (error) {
      toast.error(t("The profile could not be reset"), {
        description: why(error),
      });
      return false;
    }
    toast.success(
      t("Every site of {{project}} is signed out", { project: name }),
    );
    onChanged();
  };

  const open = async () => {
    setOpening(true);
    try {
      await api.openBrowser(name, address.trim());
    } catch (error) {
      toast.error(t("The browser could not be opened"), {
        description: why(error),
      });
    } finally {
      setOpening(false);
    }
  };

  return (
    <Card data-card="project-browser" className="gap-0 py-0">
      <CardHeader className="gap-1 px-5 pt-5 pb-2 sm:px-6">
        <CardTitle className="flex items-center gap-2 text-base">
          <Globe className="size-4" />
          {t("Browser")}
        </CardTitle>
        <CardDescription className="text-[13px] leading-relaxed">
          {t(
            "Where this project's external tickets act. Ponos's browser keeps one profile per project and signs in with the vault's logins without the model seeing their password; a second factor or a CAPTCHA is finished here, by you.",
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-5 pb-5 sm:px-6">
        <label className="flex flex-col gap-1.5 text-sm">
          <span className="font-semibold">
            {t("Browser of external tickets")}
          </span>
          <select
            className={SELECT}
            value={browser.value}
            disabled={saving}
            data-slot="project-browser-choice"
            onChange={(event) =>
              void onSave(event.target.value as "ponos" | "chrome")
            }
          >
            <option value="ponos">{t("Ponos's browser")}</option>
            <option value="chrome">{t("Claude in Chrome")}</option>
          </select>
          <span className="text-muted-foreground text-[13px]">
            {browser.own
              ? t(
                  "This project's own choice, whatever the general settings say.",
                )
              : t("Follows the general settings.")}
          </span>
        </label>
        {browser.missing ? (
          <p
            className="text-destructive text-[13px]"
            data-slot="project-browser-missing"
          >
            {t(
              "Not installed on this machine: {{why}}. External tickets use Claude in Chrome until it is (ponos doctor).",
              {
                why: browser.missing,
              },
            )}
          </p>
        ) : null}
        <div className="flex flex-col gap-1.5 text-sm">
          <span className="font-semibold">{t("Signed in to")}</span>
          {browser.sites.length ? (
            <ul
              className="flex flex-wrap gap-1.5"
              data-slot="project-browser-sites"
            >
              {browser.sites.map((site) => (
                <li key={site}>
                  <Badge variant="outline">{site}</Badge>
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-muted-foreground text-[13px]">
              {t("No site yet.")}
            </span>
          )}
          <div>
            <ConfirmDialog
              destructive
              title={t("Reset the profile of {{project}}?", { project: name })}
              description={t(
                "Its cookies are deleted: every site is signed out, and the next ticket signs in again.",
              )}
              confirm={t("Reset")}
              onConfirm={reset}
              trigger={
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!name}
                  data-slot="project-browser-reset"
                >
                  <RotateCcw />
                  {t("Reset")}
                </Button>
              }
            />
          </div>
        </div>
        <form
          className="flex flex-col gap-1.5 text-sm"
          onSubmit={(event) => {
            event.preventDefault();
            if (address.trim()) void open();
          }}
        >
          <span className="font-semibold">{t("Sign in here")}</span>
          <span className="text-muted-foreground text-[13px]">
            {t(
              "Opens the address in a browser on this project's profile, which you drive below: what you sign in to stays for its tickets.",
            )}
          </span>
          <div className="flex gap-2">
            <Input
              value={address}
              onChange={(event) => setAddress(event.target.value)}
              placeholder="https://dokploy.example.com/login"
              disabled={!!browser.missing || !name}
              data-slot="project-browser-address"
            />
            <Button
              type="submit"
              size="sm"
              disabled={
                opening || !address.trim() || !!browser.missing || !name
              }
            >
              {t("Open the page")}
            </Button>
          </div>
        </form>
        {running.map((item) => (
          <LiveView key={item.id} live={item} />
        ))}
      </CardContent>
    </Card>
  );
}

function LiveView({ live }: { live: BrowserLive }) {
  const t = useT();
  const [tick, setTick] = React.useState(0);
  const [text, setText] = React.useState("");
  const picture = React.useRef<HTMLImageElement>(null);

  React.useEffect(() => {
    const timer = window.setInterval(
      () => setTick((was) => was + 1),
      LOOK_EVERY,
    );
    return () => window.clearInterval(timer);
  }, []);

  const act = (action: Parameters<typeof api.browserAct>[1]) =>
    api
      .browserAct(live.id, action)
      .catch((error) =>
        toast.error(t("The browser did not take it"), {
          description: why(error),
        }),
      );

  const click = (event: React.MouseEvent<HTMLImageElement>) => {
    const shown = picture.current;
    if (!shown || !shown.naturalWidth) return;
    const box = shown.getBoundingClientRect();
    const scale = shown.naturalWidth / box.width;
    void act({
      action: "click",
      x: (event.clientX - box.left) * scale,
      y: (event.clientY - box.top) * scale,
    });
  };

  return (
    <section
      className="flex flex-col gap-2 rounded-md border p-3"
      data-slot="browser-live"
      data-live={live.id}
    >
      <p className="flex flex-wrap items-center gap-2 text-[13px]">
        <Badge variant={live.waiting ? "destructive" : "secondary"}>
          {live.person
            ? t("Opened here")
            : t("Ticket {{ticket}}", { ticket: live.ticket.slice(0, 8) })}
        </Badge>
        {live.waiting ? (
          <span className="text-destructive">
            {t("Stopped on {{what}}", { what: live.waiting })}
          </span>
        ) : null}
        <span className="text-muted-foreground min-w-0 truncate">
          {live.title || live.url}
        </span>
      </p>
      {/* The screen, fetched again each second; a click is played in the browser at the same place. */}
      <img
        ref={picture}
        src={`/api/browser/live/${encodeURIComponent(live.id)}/screen?at=${tick}`}
        alt={t("What the browser shows")}
        className="w-full cursor-crosshair rounded border"
        onClick={click}
      />
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (!text) return;
          void act({ action: "type", text });
          setText("");
        }}
      >
        <Input
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={t("Text to type where the cursor is")}
          autoComplete="off"
          className="min-w-40 flex-1"
          data-slot="browser-live-text"
        />
        <Button type="submit" size="sm" variant="outline">
          {t("Type it")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => void act({ action: "press", key: "Enter" })}
        >
          {t("Press Enter")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => void act({ action: "press", key: "Tab" })}
        >
          Tab
        </Button>
        {live.person ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => void act({ action: "close" })}
            data-slot="browser-live-close"
          >
            <X />
            {t("Done, close it")}
          </Button>
        ) : null}
      </form>
    </section>
  );
}
