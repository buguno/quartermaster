document.addEventListener('click', (event) => {
  if (!event.target.closest('[data-theme-toggle]')) return;
  const dark = document.documentElement.classList.toggle('dark');
  try {
    localStorage.setItem('theme', dark ? 'dark' : 'light');
  } catch (e) {}
});

// Settings page: preview the chosen theme before saving.
document.addEventListener('change', (event) => {
  if (!event.target.matches('input[name="theme"]')) return;
  const choice = event.target.value;
  const dark =
    choice === 'dark' ||
    (choice === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.classList.toggle('dark', dark);
});
