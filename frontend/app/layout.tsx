import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title: 'Fieldnotes — Financial Assistant', description: 'Evidence for your own investment decisions'};
export default function Layout({children}: {children: React.ReactNode}) {
  return <html lang="en"><body>{children}</body></html>;
}
