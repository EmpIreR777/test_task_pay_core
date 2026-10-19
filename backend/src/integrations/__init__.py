# Пакет integrations намеренно без ре-экспортов.
#
# Раньше здесь импортировался consumer: его регистрация на общем broker
# заставила бы outbox-processor подписываться на payments.new и забирать
# сообщения, которые должен обрабатывать consumer. Consumer подключается
# только в своей точке входа (src/tasks/consumer.py).
