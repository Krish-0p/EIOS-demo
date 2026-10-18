// Same-origin proxy keeps HttpOnly sessions on the dashboard host.
const DIST = "./dist";
const PORT = Number(Bun.env.PORT ?? 5173);
const UPSTREAM = Bun.env.EIOS_API_UPSTREAM ?? "http://eios-orchestrator:8000";

Bun.serve<{ upstream: WebSocket }>({
  port: PORT,
  hostname: "0.0.0.0",
  async fetch(request, server) {
    const incoming = new URL(request.url);
    const target = new URL(incoming.pathname + incoming.search, UPSTREAM);
    if (incoming.pathname.startsWith("/api/")) {
      const headers = new Headers(request.headers);
      headers.delete("host");
      try {
        return await fetch(target, { method: request.method, headers,
          body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body, redirect: "manual" });
      } catch {
        return Response.json({ detail: "EIOS API unavailable" }, { status: 502 });
      }
    }
    if (incoming.pathname === "/ws") {
      target.protocol = target.protocol === "https:" ? "wss:" : "ws:";
      const upstream = new WebSocket(target, { headers: {
        cookie: request.headers.get("cookie") ?? "",
        origin: request.headers.get("origin") ?? "",
      } });
      try {
        await new Promise<void>((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error("WebSocket timed out")), 10000);
          upstream.onopen = () => { clearTimeout(timer); resolve(); };
          upstream.onerror = () => { clearTimeout(timer); reject(new Error("WebSocket unavailable")); };
          upstream.onclose = () => { clearTimeout(timer); reject(new Error("WebSocket rejected")); };
        });
      } catch {
        upstream.close();
        return new Response("WebSocket authentication or connection failed", { status: 401 });
      }
      if (server.upgrade(request, { data: { upstream } })) return;
      upstream.close();
      return new Response("Upgrade failed", { status: 400 });
    }
    const candidate = incoming.pathname === "/" ? "/index.html" : incoming.pathname;
    let file = Bun.file(DIST + candidate);
    if (!(await file.exists())) file = Bun.file(DIST + "/index.html");
    return new Response(file);
  },
  websocket: {
    open(client) {
      const upstream = client.data.upstream;
      upstream.onmessage = event => client.send(event.data);
      upstream.onclose = event => client.close(event.code === 1006 ? 1011 : event.code, event.reason);
      upstream.onerror = () => client.close(1011, "Backend connection lost");
    },
    message(client, message) { if (client.data.upstream.readyState === WebSocket.OPEN) client.data.upstream.send(message); },
    close(client) { client.data.upstream.close(); },
  },
});
console.log(`dashboard listening on ${PORT}`);
