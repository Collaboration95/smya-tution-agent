import "./globals.css";
export const metadata = { title: "SMYA Co-Tutor", description: "Tuition centre co-tutor — S1 vertical slice" };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased">
        <header className="border-b bg-white">
          <div className="mx-auto max-w-5xl px-4 py-3 flex items-center justify-between">
            <span className="font-semibold">SMYA — S1 Diagnostic Proof</span>
            <a href="/health" className="text-sm text-blue-600 hover:underline">Health</a>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
