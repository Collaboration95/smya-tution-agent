import "./globals.css";
export const metadata = { title: "SMYA Co-Tutor", description: "Evidence-led practice for a tuition-centre workflow" };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="site-body">
        <header className="site-header">
          <div className="site-header__inner">
            <a href="/" className="brand"><span className="brand__mark">SMYA</span><span>Co-Tutor</span><span className="brand__caption">practice workspace</span></a>
            <nav className="site-nav" aria-label="Primary navigation">
              <a href="/student">Student practice</a>
              <a href="/tutor">Tutor jobs</a>
              <a href="/health">Health</a>
            </nav>
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
