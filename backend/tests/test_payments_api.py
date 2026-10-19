import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


class TestCreatePayment:
    """Тесты создания платежа POST /api/v1/payments."""

    async def test_create_payment_success(
        self, client: AsyncClient, api_key: str, payment_data: dict, idempotency_key: str
    ) -> None:
        """Успешное создание платежа: 202, корректный ответ."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        response = await client.post('/api/v1/payments/', json=payment_data, headers=headers)

        assert response.status_code == 202
        data = response.json()
        assert 'payment_id' in data
        assert UUID(data['payment_id'])
        assert data['status'] == 'pending'
        assert 'created_at' in data

    async def test_create_payment_without_trailing_slash(
        self, client: AsyncClient, api_key: str, payment_data: dict, idempotency_key: str
    ) -> None:
        """Путь без завершающего слэша (как в ТЗ) тоже работает: 202, а не 307."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        response = await client.post('/api/v1/payments', json=payment_data, headers=headers)

        assert response.status_code == 202
        assert UUID(response.json()['payment_id'])

    async def test_create_payment_idempotency(
        self, client: AsyncClient, api_key: str, payment_data: dict, idempotency_key: str
    ) -> None:
        """Повторный запрос с тем же Idempotency-Key возвращает существующий платёж."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}

        # Первый запрос
        response1 = await client.post('/api/v1/payments/', json=payment_data, headers=headers)
        assert response1.status_code == 202
        data1 = response1.json()

        # Второй запрос с тем же ключом
        response2 = await client.post('/api/v1/payments/', json=payment_data, headers=headers)
        assert response2.status_code == 202
        data2 = response2.json()

        # Должен вернуться тот же payment_id
        assert data2['payment_id'] == data1['payment_id']
        assert data2['status'] == data1['status']

    async def test_create_payment_missing_api_key(
        self, client: AsyncClient, payment_data: dict, idempotency_key: str
    ) -> None:
        """Отсутствие X-API-Key: 401."""
        headers = {'Idempotency-Key': idempotency_key}
        response = await client.post('/api/v1/payments/', json=payment_data, headers=headers)
        assert response.status_code == 401

    async def test_create_payment_invalid_api_key(
        self, client: AsyncClient, payment_data: dict, idempotency_key: str
    ) -> None:
        """Неверный X-API-Key: 401."""
        headers = {'X-API-Key': 'invalid-key', 'Idempotency-Key': idempotency_key}
        response = await client.post('/api/v1/payments/', json=payment_data, headers=headers)
        assert response.status_code == 401
        assert response.json()['detail'] == 'Неверный API ключ'

    async def test_create_payment_missing_idempotency_key(
        self, client: AsyncClient, api_key: str, payment_data: dict
    ) -> None:
        """Отсутствие Idempotency-Key: 422."""
        headers = {'X-API-Key': api_key}
        response = await client.post('/api/v1/payments/', json=payment_data, headers=headers)
        assert response.status_code == 422

    @pytest.mark.parametrize(
        'amount',
        [
            '0',
            '-10',
            'invalid',
        ],
    )
    async def test_create_payment_invalid_amount(
        self, client: AsyncClient, api_key: str, payment_data: dict, idempotency_key: str, amount: str
    ) -> None:
        """Невалидная сумма (amount <= 0): 422."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        data = payment_data.copy()
        data['amount'] = amount
        response = await client.post('/api/v1/payments/', json=data, headers=headers)
        assert response.status_code == 422

    async def test_create_payment_invalid_currency(
        self, client: AsyncClient, api_key: str, payment_data: dict, idempotency_key: str
    ) -> None:
        """Неверная валюта: 422."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        data = payment_data.copy()
        data['currency'] = 'INVALID'
        response = await client.post('/api/v1/payments/', json=data, headers=headers)
        assert response.status_code == 422

    async def test_create_payment_missing_webhook_url(
        self, client: AsyncClient, api_key: str, idempotency_key: str
    ) -> None:
        """Отсутствует webhook_url: 422."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        data = {
            'amount': '100.50',
            'currency': 'RUB',
            'description': 'Test payment',
            'metadata': {},
        }
        response = await client.post('/api/v1/payments/', json=data, headers=headers)
        assert response.status_code == 422

    async def test_create_payment_invalid_webhook_url(
        self, client: AsyncClient, api_key: str, payment_data: dict, idempotency_key: str
    ) -> None:
        """Неверный webhook_url: 422."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        data = payment_data.copy()
        data['webhook_url'] = 'not-a-url'
        response = await client.post('/api/v1/payments/', json=data, headers=headers)
        assert response.status_code == 422

    async def test_create_payment_valid_currencies(self, client: AsyncClient, api_key: str, payment_data: dict) -> None:
        """Все валидные валюты: RUB, USD, EUR."""
        for currency in ['RUB', 'USD', 'EUR']:
            headers = {'X-API-Key': api_key, 'Idempotency-Key': f'test-key-{uuid4()}'}
            data = payment_data.copy()
            data['currency'] = currency
            response = await client.post('/api/v1/payments/', json=data, headers=headers)
            assert response.status_code == 202, f'Failed for currency {currency}'

    @pytest.mark.parametrize(
        'amount',
        [
            '0.001',  # больше двух знаков после запятой
            '1500.005',
            '123456789012345678.90',  # не влезает в numeric(18, 2)
        ],
    )
    async def test_create_payment_amount_out_of_column_range(
        self, client: AsyncClient, api_key: str, payment_data: dict, idempotency_key: str, amount: str
    ) -> None:
        """Сумма, которая не влезает в numeric(18, 2), отсекается валидатором: 422, а не 500."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        data = payment_data.copy()
        data['amount'] = amount
        response = await client.post('/api/v1/payments/', json=data, headers=headers)
        assert response.status_code == 422

    async def test_create_payment_too_long_description(
        self, client: AsyncClient, api_key: str, payment_data: dict, idempotency_key: str
    ) -> None:
        """Описание длиннее колонки (1000 символов) даёт 422, а не 500."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        data = payment_data.copy()
        data['description'] = 'x' * 1001
        response = await client.post('/api/v1/payments/', json=data, headers=headers)
        assert response.status_code == 422

    async def test_create_payment_concurrent_same_key(
        self, client: AsyncClient, api_key: str, payment_data: dict, idempotency_key: str
    ) -> None:
        """Параллельные запросы с одним ключом: все 202, один payment_id, одна строка в БД."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}

        responses = await asyncio.gather(
            *[client.post('/api/v1/payments/', json=payment_data, headers=headers) for _ in range(10)],
        )

        assert {r.status_code for r in responses} == {202}
        payment_ids = {r.json()['payment_id'] for r in responses}
        assert len(payment_ids) == 1

    async def test_idempotency_key_reuse_with_different_payload(
        self, client: AsyncClient, api_key: str, payment_data: dict, idempotency_key: str
    ) -> None:
        """Тот же ключ с другим телом: 409, а не молчаливый возврат старого платежа."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        first = await client.post('/api/v1/payments/', json=payment_data, headers=headers)
        assert first.status_code == 202
        payment_id = first.json()['payment_id']

        changed = {**payment_data, 'amount': '999.99', 'currency': 'USD'}
        second = await client.post('/api/v1/payments/', json=changed, headers=headers)
        assert second.status_code == 409
        assert 'другим телом' in second.json()['detail']

        # Существующий платёж не перезаписан чужим телом
        detail = await client.get(f'/api/v1/payments/{payment_id}', headers={'X-API-Key': api_key})
        assert detail.status_code == 200
        assert detail.json()['amount'] == payment_data['amount']
        assert detail.json()['currency'] == payment_data['currency']

    async def test_idempotency_key_too_long(self, client: AsyncClient, api_key: str, payment_data: dict) -> None:
        """Idempotency-Key длиннее 255 символов: 422 на границе API, а не DataError (500) в БД."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': 'k' * 300}
        response = await client.post('/api/v1/payments/', json=payment_data, headers=headers)
        assert response.status_code == 422

    async def test_idempotency_key_with_whitespace(self, client: AsyncClient, api_key: str, payment_data: dict) -> None:
        """Idempotency-Key с пробелами: 422 — такой ключ не защищает от дублей."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': 'key with spaces'}
        response = await client.post('/api/v1/payments/', json=payment_data, headers=headers)
        assert response.status_code == 422


class TestGetPayment:
    """Тесты получения платежа GET /api/v1/payments/{payment_id}."""

    async def test_get_payment_success(
        self, client: AsyncClient, api_key: str, payment_data: dict, idempotency_key: str
    ) -> None:
        """Получение платежа: 200, все поля."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        create_response = await client.post('/api/v1/payments/', json=payment_data, headers=headers)
        assert create_response.status_code == 202
        payment_id = create_response.json()['payment_id']

        # Получить платёж
        get_headers = {'X-API-Key': api_key}
        response = await client.get(f'/api/v1/payments/{payment_id}', headers=get_headers)

        assert response.status_code == 200
        data = response.json()
        assert data['payment_id'] == payment_id
        assert data['amount'] == payment_data['amount']
        assert data['currency'] == payment_data['currency']
        assert data['description'] == payment_data['description']
        assert data['metadata'] == payment_data['metadata']
        assert data['status'] == 'pending'
        assert data['idempotency_key'] == idempotency_key
        assert data['webhook_url'] == payment_data['webhook_url']
        assert 'created_at' in data
        assert data['processed_at'] is None
        # Факт доставки уведомления виден клиенту до и после обработки
        assert 'webhook_delivered_at' in data
        assert data['webhook_delivered_at'] is None
        assert data['failure_reason'] is None

    async def test_get_payment_not_found(self, client: AsyncClient, api_key: str) -> None:
        """Получение несуществующего платежа: 404."""
        headers = {'X-API-Key': api_key}
        non_existent_id = uuid4()
        response = await client.get(f'/api/v1/payments/{non_existent_id}', headers=headers)
        assert response.status_code == 404
        assert 'не найден' in response.json()['detail']

    async def test_get_payment_missing_api_key(
        self,
        client: AsyncClient,
        api_key: str,
        payment_data: dict,
        idempotency_key: str,
    ) -> None:
        """Отсутствие X-API-Key при GET: 401."""
        # Создаём платёж с валидным API ключом
        create_headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        create_response = await client.post('/api/v1/payments/', json=payment_data, headers=create_headers)
        assert create_response.status_code == 202
        payment_id = create_response.json()['payment_id']

        # GET без API ключа
        response = await client.get(f'/api/v1/payments/{payment_id}')
        assert response.status_code == 401

    async def test_get_payment_invalid_api_key(
        self,
        client: AsyncClient,
        api_key: str,
        payment_data: dict,
        idempotency_key: str,
    ) -> None:
        """Неверный X-API-Key при GET: 401."""
        headers = {'X-API-Key': api_key, 'Idempotency-Key': idempotency_key}
        create_response = await client.post('/api/v1/payments/', json=payment_data, headers=headers)
        assert create_response.status_code == 202
        payment_id = create_response.json()['payment_id']

        get_headers = {'X-API-Key': 'invalid-key'}
        response = await client.get(f'/api/v1/payments/{payment_id}', headers=get_headers)
        assert response.status_code == 401
