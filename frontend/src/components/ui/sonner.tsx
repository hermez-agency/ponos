import { Toaster as Sonner, type ToasterProps } from "sonner"

import { Robot } from "@/components/console/robot"
import { useTheme } from "@/hooks/use-theme"

/* shadcn's Toaster, with `next-themes` taken out of it: this console is not
 * Next, and the theme is one class on <html> and a line in localStorage.
 *
 * A toast that went well or badly wears the robot in that mood rather than a
 * tick or a cross — the sentence beside it still says which. */
const ICONS: ToasterProps["icons"] = {
  success: <Robot state="success" size={20} />,
  error: <Robot state="error" size={20} />,
}

function Toaster({ ...props }: ToasterProps) {
  const { theme } = useTheme()

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      position="bottom-right"
      // Above the button that opens the conversation (`talk-drawer.tsx`): a
      // toast that stays — "New version available" — took every click meant
      // for it, and covered the send button of the drawer once open. On a
      // phone the bottom bar is the navigation, so above that as well.
      offset={{ bottom: "5rem" }}
      mobileOffset={{ bottom: "calc(var(--bottom-nav) + 5rem)" }}
      icons={ICONS}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
