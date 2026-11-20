/* The French of « Scheduled for »: the picker's shortcuts, and what is said
   around it in the New ticket dialog and a ticket's view (`schedule-picker.tsx`).

   Apart from `french.ts`, as `ticket-french.ts` is, and fetched when the
   picker is drawn: the first load of a French page is held to a budget
   (tests/test_release.py), and the board itself says none of these. Same
   rule as there: the English sentence is the key. */

export const LATER_FRENCH: Record<string, string> = {
  "Scheduled for": "Programmé pour",
  "In 1 h": "Dans 1 h",
  Tonight: "Ce soir",
  "Tomorrow morning": "Demain matin",
  "The day after tomorrow": "Après-demain",
  "Next Monday": "Lundi prochain",
  Shortcuts: "Raccourcis",
  "Date and hour": "Date et heure",
  "Remove the date": "Retirer la date",
  "Launched, the ticket waits until {{at}}.": "Lancé, le ticket attend le {{at}}.",
  "This moment has already passed: choose a later one, or none.":
    "Ce moment est déjà passé : choisissez-en un plus tard, ou aucun.",
}
