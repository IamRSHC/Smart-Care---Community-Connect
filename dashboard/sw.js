// SmartCare service worker - handles push notifications only.
// This runs in the background even when the dashboard tab/browser is
// closed, which is the whole point: staff don't need the app open.

self.addEventListener('push', (event) => {
  let payload = { title: 'SmartCare', body: 'New alert' };
  try {
    if (event.data) payload = event.data.json();
  } catch (e) {
    // fall back to defaults above if the payload isn't valid JSON
  }

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: 'icon.png',
      badge: 'icon.png',
      vibrate: [200, 100, 200],
      tag: 'smartcare-alert',
      renotify: true,
    })
  );
});

// Tapping the notification focuses an existing dashboard tab if one's
// open, or opens a new one - either way it lands on the live dashboard.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes('app.html') && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow('/app.html');
      }
    })
  );
});
