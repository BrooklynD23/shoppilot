// Shared by StepRow.astro (server render) and demo.ts (client replay), so both
// paths print the same pill, money and approve text for a step.
const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
export const money = (cents: number) => usd.format(cents / 100);

export type StepIn = {
  title: string;
  target: string;
  amountCents: number | null;
  movesMoney: boolean;
  undoable: boolean;
};

export function stepView(s: StepIn) {
  const amt = s.amountCents == null ? null : money(s.amountCents);
  const order = s.title.match(/\d+/)?.[0] ?? '';
  return {
    // Data uses " · " separators; the landing bans dot meta strings.
    target: s.target.replaceAll(' · ', ', '),
    state: s.movesMoney ? 'approval' : 'checked',
    pill: s.movesMoney ? 'Needs approval' : 'Checked',
    money: amt == null ? 'No money moves' : s.movesMoney ? `${amt} out` : `Est. ${amt}, not charged`,
    moneyKind: amt == null ? 'none' : s.movesMoney ? 'out' : 'est',
    // ponytail: refund_order is the only tool that moves money, so the label names a refund.
    approve: s.movesMoney ? `Approve refund of ${amt} on order ${order}. Card refunds cannot be undone.` : 'Run this step',
    checked: !s.movesMoney,
    irreversible: s.movesMoney && !s.undoable,
  };
}
