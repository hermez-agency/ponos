/* Which ticket an address names. The console keys a ticket by its id of
 * thirty-two characters, and an address may say it in the other ways a person
 * does: its public id (`PON-142`, in any case) or the eight last characters.
 * Plain data in, plain data out, and nothing imported, so that `node --test`
 * reads it as it stands. */

export interface Referable {
  id: string
  short: string
  public_id?: string
}

/** The ticket a reference names — by id, public id or short id — or undefined. */
export function ticketNamed<T extends Referable>(tickets: T[], reference: string): T | undefined {
  const wanted = reference.trim().toLowerCase()
  if (!wanted) return undefined
  const exact = tickets.find((ticket) => ticket.id === wanted)
  if (exact) return exact
  const said = tickets.find((ticket) => ticket.public_id && ticket.public_id.toLowerCase() === wanted)
  if (said) return said
  if (!/^[0-9a-f]{8}$/.test(wanted)) return undefined
  const shorts = tickets.filter((ticket) => ticket.short.toLowerCase() === wanted)
  return shorts.length === 1 ? shorts[0] : undefined
}
