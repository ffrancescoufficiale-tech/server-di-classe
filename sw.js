self.addEventListener('fetch', (event) => {
  // Lasciamo passare tutte le richieste normalmente alla rete
  event.respondWith(fetch(event.request));
});