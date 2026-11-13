// Let HTMX swap validation (422) and domain-rule (409) responses into the page.
document.addEventListener('htmx:beforeSwap', (event) => {
  const status = event.detail.xhr.status;
  if (status === 409 || status === 422) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});

// Modals use the native <dialog> element.
document.addEventListener('click', (event) => {
  const opener = event.target.closest('[data-modal-open]');
  if (opener) {
    document.getElementById(opener.dataset.modalOpen).showModal();
    return;
  }
  if (event.target.closest('[data-modal-close]')) {
    event.target.closest('dialog').close();
    return;
  }
  // A click on the backdrop targets the <dialog> itself.
  if (event.target.matches('dialog.modal')) event.target.close();
});

// Reopen dialogs that came back with validation errors.
function openPendingModals() {
  document.querySelectorAll('dialog[data-open]').forEach((dialog) => {
    dialog.removeAttribute('data-open');
    dialog.showModal();
  });
}
document.addEventListener('DOMContentLoaded', openPendingModals);
document.addEventListener('htmx:afterSettle', openPendingModals);

// Selects marked data-autosubmit submit their form on change (language picker).
document.addEventListener('change', (event) => {
  if (event.target.matches('[data-autosubmit]')) event.target.form.submit();
});

// Sidebar (mobile drawer): the menu button opens it, the overlay, Esc or a link closes it.
function setSidebar(open) {
  document.getElementById('sidebar')?.toggleAttribute('data-open', open);
  document.getElementById('sidebar-overlay')?.toggleAttribute('data-open', open);
}
document.addEventListener('click', (event) => {
  if (event.target.closest('[data-sidebar-toggle]')) setSidebar(true);
  else if (event.target.closest('[data-sidebar-close]')) setSidebar(false);
  else if (event.target.closest('#sidebar a')) setSidebar(false);
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') setSidebar(false);
});

// Dropdown menus built on <details data-menu> close when you click elsewhere.
document.addEventListener('click', (event) => {
  document.querySelectorAll('details[data-menu][open]').forEach((menu) => {
    if (!menu.contains(event.target)) menu.removeAttribute('open');
  });
});

// Print buttons; paper is always printed with the light theme.
document.addEventListener('click', (event) => {
  if (event.target.closest('[data-print]')) window.print();
});
let darkBeforePrint = false;
window.addEventListener('beforeprint', () => {
  darkBeforePrint = document.documentElement.classList.contains('dark');
  document.documentElement.classList.remove('dark');
});
window.addEventListener('afterprint', () => {
  if (darkBeforePrint) document.documentElement.classList.add('dark');
});
