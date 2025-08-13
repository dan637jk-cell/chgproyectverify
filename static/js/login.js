document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('login-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        const errorMessage = document.getElementById('error-message');

        try {
            const response = await fetch('/login_action', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ username, password }),
            });

            const result = await response.json();

            if (response.ok && result.success) {
                window.location.href = '/chat';
            } else {
                const title = (window.i18n && i18n.t) ? i18n.t('error_title') : 'Error';
                errorMessage.textContent = `${title}: ${result.error}`;
            }
        } catch (error) {
            errorMessage.textContent = (window.i18n && i18n.t) ? i18n.t('network_error') : 'An unexpected error occurred. Please try again.';
            console.error('Login error:', error);
        }
    });
});
