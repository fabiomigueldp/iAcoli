// JavaScript for the conversational agent dashboard
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('agent-form');
    const input = document.getElementById('agent-input');
    const history = document.getElementById('agent-history');
    const typingIndicator = document.getElementById('agent-typing');
    const refreshButton = document.getElementById('agent-refresh-calendar');
    const submitButton = form ? form.querySelector('button[type="submit"]') : null;
    let calendar;

    function createParagraphs(text) {
        const fragment = document.createDocumentFragment();
        const lines = (text || '').split(/\n+/);
        lines.forEach((line, index) => {
            const paragraph = document.createElement('p');
            paragraph.className = 'mb-0';
            paragraph.textContent = line.trim() || ' ';
            if (index < lines.length - 1) {
                paragraph.classList.add('mb-1');
            }
            fragment.appendChild(paragraph);
        });
        return fragment;
    }

    function statusToColor(status) {
        const map = {
            success: 'success',
            validation_error: 'warning',
            error: 'danger',
            noop: 'secondary'
        };
        return map[status] || 'secondary';
    }

    function createActionsList(actions) {
        if (!Array.isArray(actions) || actions.length === 0) {
            return null;
        }
        const container = document.createElement('div');
        container.className = 'executed-actions mt-2';

        const heading = document.createElement('small');
        heading.className = 'text-muted d-block fw-semibold';
        heading.textContent = 'Acoes executadas';
        container.appendChild(heading);

        const list = document.createElement('ul');
        list.className = 'list-unstyled mb-0 small';

        actions.forEach(action => {
            const item = document.createElement('li');
            item.className = 'd-flex flex-column mb-1';

            const row = document.createElement('div');
            row.className = 'd-flex align-items-center gap-2';

            const badge = document.createElement('span');
            badge.className = `badge bg-${statusToColor(action.status)}`;
            badge.textContent = action.status || 'info';
            row.appendChild(badge);

            const endpoint = document.createElement('span');
            endpoint.textContent = action.endpoint || 'endpoint desconhecido';
            row.appendChild(endpoint);

            item.appendChild(row);

            if (action.error) {
                const error = document.createElement('small');
                error.className = 'text-danger ms-4';
                error.textContent = action.error;
                item.appendChild(error);
            } else if (action.result && typeof action.result === 'object' && !Array.isArray(action.result) && action.result.detail) {
                const detail = document.createElement('small');
                detail.className = 'text-muted ms-4';
                detail.textContent = action.result.detail;
                item.appendChild(detail);
            }

            list.appendChild(item);
        });

        container.appendChild(list);
        return container;
    }

    function appendMessage(author, text, extraContent = null) {
        if (!history) {
            return;
        }
        const wrapper = document.createElement('div');
        wrapper.className = `chat-message ${author}`;

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.appendChild(createParagraphs(text));
        wrapper.appendChild(bubble);

        if (extraContent) {
            wrapper.appendChild(extraContent);
        }

        history.appendChild(wrapper);
        history.scrollTop = history.scrollHeight;
    }

    function setTyping(visible) {
        if (!typingIndicator) {
            return;
        }
        typingIndicator.style.display = visible ? 'block' : 'none';
    }

    function setFormDisabled(disabled) {
        if (input) {
            input.disabled = disabled;
        }
        if (submitButton) {
            submitButton.disabled = disabled;
        }
    }

    async function sendMessage(event) {
        event.preventDefault();
        if (!form) {
            return;
        }
        const text = (input?.value || '').trim();
        if (!text) {
            return;
        }

        appendMessage('user', text);
        input.value = '';
        setTyping(true);
        setFormDisabled(true);

        try {
            const response = await fetch('/api/agent/interact', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: text })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            const actionsList = createActionsList(data.executed_actions);
            appendMessage('agent', data.response_text || 'Tudo certo.', actionsList);

            if (calendar) {
                calendar.refetchEvents();
            }
        } catch (error) {
            console.error('Agent request failed:', error);
            appendMessage('agent', 'Nao consegui concluir a solicitacao. Tente novamente em instantes.');
            if (window.Dashboard && typeof window.Dashboard.showNotification === 'function') {
                window.Dashboard.showNotification('Nao foi possivel falar com o agente agora.', 'danger');
            }
        } finally {
            setTyping(false);
            setFormDisabled(false);
            input?.focus();
        }
    }

    function initCalendar() {
        const calendarEl = document.getElementById('agent-calendar');
        if (!calendarEl || typeof FullCalendar === 'undefined') {
            return;
        }

        calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            locale: 'pt-br',
            height: '100%',
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: 'dayGridMonth,timeGridWeek,timeGridDay'
            },
            events: async (info, success, failure) => {
                try {
                    const params = new URLSearchParams({
                        start: info.startStr.slice(0, 10),
                        end: info.endStr.slice(0, 10)
                    });
                    const response = await fetch(`/api/events?${params.toString()}`);
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    const events = await response.json();
                    const items = events.map(event => ({
                        id: event.id,
                        title: `${event.community} • ${event.kind}`,
                        start: event.dtstart,
                        end: event.dtend,
                        extendedProps: event
                    }));
                    success(items);
                } catch (error) {
                    console.error('Failed to load events for calendar:', error);
                    failure(error);
                    if (window.Dashboard && typeof window.Dashboard.showNotification === 'function') {
                        window.Dashboard.showNotification('Falha ao carregar eventos do calendario.', 'warning');
                    }
                }
            }
        });

        calendar.render();
    }

    if (form) {
        form.addEventListener('submit', sendMessage);
    }
    if (refreshButton) {
        refreshButton.addEventListener('click', event => {
            event.preventDefault();
            if (calendar) {
                calendar.refetchEvents();
                if (window.Dashboard && typeof window.Dashboard.showNotification === 'function') {
                    window.Dashboard.showNotification('Calendario atualizado.', 'info', 3000);
                }
            }
        });
    }

    initCalendar();
    appendMessage('agent', 'Ola! Como posso ajudar com a agenda hoje?');
});
