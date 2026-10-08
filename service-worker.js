self.addEventListener("push", (event) => {
    if (!event.data) return;

    let payload;
    try {
        payload = event.data.json();
    } catch {
        payload = { title: "New job match", body: event.data.text() };
    }

    event.waitUntil(
        self.registration.showNotification(payload.title || "New job match", {
            body: payload.body || "A new job matches the shared search profile.",
            icon: "/icon.svg",
            data: { url: payload.url || "/" }
        })
    );
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const destination = new URL(event.notification.data?.url || "/", self.location.origin);
    if (destination.origin !== self.location.origin) return;

    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
            const existing = clients.find(
                (client) => new URL(client.url).origin === self.location.origin
            );
            if (existing) return existing.focus();
            return self.clients.openWindow(destination.href);
        })
    );
});
