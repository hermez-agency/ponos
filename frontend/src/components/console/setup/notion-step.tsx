import * as React from "react";
import { ArrowRight } from "lucide-react";

import { Said, StepCard } from "@/components/console/setup/bits";
import { useKnown } from "@/components/console/setup/known";
import { NotionIntegration } from "@/components/console/setup/notion-integration";
import { NotionPlace } from "@/components/console/setup/notion-place";
import { NotionShare } from "@/components/console/setup/notion-share";
import { Button } from "@/components/ui/button";
import { api, why } from "@/lib/api";
import { counted, useT } from "@/lib/i18n";
import type { Provisioned, Shared, Summary } from "@/lib/types";

/* -- 3. notion -------------------------------------------------------------- */

export function NotionStep({ onNext }: { onNext: () => void }) {
  const t = useT();
  const [board, setBoard] = React.useState<Summary["board"] | null>(null);
  const [token, setToken] = React.useState("");
  const [shared, setShared] = React.useState<Shared | null>(null);
  const [page, setPage] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [done, setDone] = React.useState<Provisioned | null>(null);
  const [problem, setProblem] = React.useState("");
  const { summary, reread } = useKnown();

  React.useEffect(() => {
    if (summary) setBoard(summary.board);
  }, [summary]);

  React.useEffect(() => {
    // A token already written — a step left half-way, a reload — is asked again.
    void api.sharedWithNotion("").then(
      (answer) => answer.ok && setShared(answer),
      () => undefined,
    );
  }, []);

  const found = board?.state === "ok";
  const waiting = Boolean(
    shared?.ok && !found && !shared.pages.length && !shared.boards.length,
  );

  // Nothing shared yet: somebody is in Notion adding the integration to a page,
  // and the page appears here on its own as soon as they have.
  React.useEffect(() => {
    if (!waiting) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void api.sharedWithNotion("").then(
        (answer) => answer.ok && setShared(answer),
        () => undefined,
      );
    }, 4000);
    return () => window.clearInterval(timer);
  }, [waiting]);

  const check = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      const answer = await api.sharedWithNotion(token.trim());
      setShared(answer);
      if (answer.ok) setToken("");
    } catch (error) {
      setProblem(why(error));
    } finally {
      setBusy(false);
    }
  };

  const build = async (chosen: { page?: string; workspace?: string }) => {
    setBusy(true);
    setProblem("");
    setDone(null);
    try {
      const answer = await api.saveNotion({
        token: "",
        page: chosen.page ?? "",
        workspace: chosen.workspace,
      });
      setDone(answer);
      setBoard(answer.board);
      reread();
    } catch (error) {
      setProblem(why(error));
    } finally {
      setBusy(false);
    }
  };

  const footer = (
    <Button
      type="button"
      variant={found ? "default" : "outline"}
      onClick={onNext}
    >
      {t("Continue")}
      <ArrowRight />
    </Button>
  );

  return (
    <StepCard
      title={t("The board")}
      blurb={t(
        "Ponos keeps your tickets itself. Connecting a Notion board is optional, and you can do it later in the settings.",
      )}
      footer={footer}
    >
      {/* Only once there is one: before, what is missing is what the three
          gestures below are about, and the configuration's own words for it
          would only alarm somebody who has not started yet. */}
      {found ? (
        <Said
          ok
          text={counted(
            board.tickets ?? 0,
            "A board is connected: {{count}} ticket on it.",
            "A board is connected: {{count}} tickets on it.",
          )}
        />
      ) : board?.state === "error" ? (
        <Said ok={false} text={board.said} />
      ) : null}

      <NotionIntegration
        token={token}
        shared={shared}
        busy={busy}
        onType={setToken}
        onCheck={(event) => void check(event)}
      />
      {shared?.ok ? <NotionShare name={shared.name || "Ponos"} /> : null}
      {shared?.ok ? (
        <NotionPlace
          shared={shared}
          waiting={waiting}
          found={found}
          page={page}
          busy={busy}
          done={done}
          onPage={setPage}
          onBuild={(chosen) => void build(chosen)}
        />
      ) : null}
      <Said ok={false} text={problem} />
    </StepCard>
  );
}
