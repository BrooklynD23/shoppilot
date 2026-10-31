// Site-wide navigation, footer and links. URLs not yet known are null and render as "pending".
export const nav = [
  { label: 'Product', href: '/#product', secondary: true },
  { label: 'How it works', href: '/how-it-works/' },
  { label: 'Report', href: '/report/', secondary: true },
  { label: 'Pricing', href: '/#pricing', secondary: true },
];
export const cta = { label: 'Try the live demo', href: '/app/' };

export const links = {
  repo: null as string | null,       // GitHub repo URL: pending (no git remote yet)
  video: null as string | null,      // YouTube demo video: pending
  deployed: null as string | null,   // Render URL: pending
};

export const footer = {
  links: [
    { label: 'App', href: '/app/' },
    { label: 'How it works', href: '/how-it-works/' },
    { label: 'Report', href: '/report/' },
  ],
  course: 'ShopPilot+ is a CS4680 course project and a student startup simulation. Nothing is for sale.',
  built: 'Built with Claude by Anthropic and Stripe.', // text only, no logos
  veo: 'Background footage is AI-generated (Google Veo).',
};
