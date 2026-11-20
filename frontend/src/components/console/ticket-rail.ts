/* Where a ticket's view has room for its rail — the column of its status,
 * facts and pull request beside the tabs (`TicketPage`).
 *
 * On its own: the window over the board reads the first to widen itself, and
 * the board is the first load, which the ticket's page is not.
 *
 * The window is 48rem wide under 64rem of screen: a rail of 17rem there would
 * leave the result and the discussion two thirds of it. From 64rem, the window
 * is 64rem, and the tabs keep what they had (about 44rem) beside the rail. The
 * page has the console's sidebar beside it: the same room, from 80rem. Under
 * those, one column, the rail's blocks above the tabs and the facts folded
 * under « Details » — what a phone draws.
 */

/** The screen on which the ticket's window is wide, and has its rail. */
export const TICKET_RAIL_WINDOW = "(width >= 64rem)"

/** The screen on which the ticket's own page has its rail. */
export const TICKET_RAIL_PAGE = "(width >= 80rem)"
