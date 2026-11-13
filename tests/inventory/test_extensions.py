from django.test import RequestFactory
from django.urls import reverse

from apps.inventory import extensions
from apps.medications.models import Medication


def test_plain_items_offer_every_extension(auth_client, item):
    url = reverse('inventory:item_detail', args=[item.pk])
    response = auth_client.get(url)

    links = response.context['attach_links']
    assert len(links) == len(extensions.EXTENSIONS)
    assert response.context['panels'] == []
    assert reverse('medications:edit', args=[item.pk]) in {
        url for _label, url in links
    }


def test_panels_hide_the_attach_links(auth_client, item):
    Medication.objects.create(item=item, active_ingredient='dipyrone')

    url = reverse('inventory:item_detail', args=[item.pk])
    response = auth_client.get(url)

    assert len(response.context['panels']) == 1
    assert 'attach_links' not in response.context


def test_dashboard_widgets_skip_empty_results(monkeypatch):
    monkeypatch.setattr(
        extensions,
        'DASHBOARD_WIDGETS',
        [lambda request: '<p>one</p>', lambda request: None],
    )

    html = extensions.render_dashboard_widgets(RequestFactory().get('/'))

    assert html == ['<p>one</p>']


def test_register_dashboard_widget(monkeypatch):
    monkeypatch.setattr(extensions, 'DASHBOARD_WIDGETS', [])

    def widget(request):
        return None

    extensions.register_dashboard_widget(widget)

    assert extensions.DASHBOARD_WIDGETS == [widget]


def _item_page(client, item):
    """The item page's own content, without the shared top bar."""
    page = client.get(
        reverse('inventory:item_detail', args=[item.pk])
    ).content.decode()
    return page.split('<main', 1)[1]


def test_item_page_groups_the_options_in_one_menu(auth_client, item):
    page = _item_page(auth_client, item)

    assert page.count('data-menu') == 1
    assert 'Tipo do item' in page
    assert 'Adicionar dados de medicamento' in page
    assert 'Adicionar dados de munição' in page


def test_item_page_has_no_menu_once_it_has_a_type(auth_client, item):
    Medication.objects.create(item=item, active_ingredient='dipyrone')

    page = _item_page(auth_client, item)

    assert 'data-menu' not in page
    assert 'Tipo do item' not in page
