                    const result = await response.json();
                    
                    if (result.success) {
                        // Clear unsaved changes flag
                        hasUnsavedChanges = false;
                        
                        showAlert(t('config.save_success'), 'success');
                        // The timezone changed and tasks still run in the old one.
                        // A task carries its own zone, so this save did not touch
                        // it - and whether it should is the operator's call, not
                        // ours: "10:00" can mean "10:00 wherever I am" or "10:00
                        // in Berlin, because that is when the other end is awake".
                        // So ask, and reload only once the answer is in.
                        if (result.timezone_question) {
                            const q = result.timezone_question;
                            const body = t('web.timezone.question_body')
                                .replace('{count}', q.tasks)
                                .replace('{old}', q.old)
                                .replace('{new}', q.new);
                            // Confirm: OK keeps the clock time, Cancel keeps the moment.
                            const keepClock = window.confirm(
                                t('web.timezone.question_title') + '\n\n' + body + '\n\n' +
                                'OK: ' + t('web.timezone.keep_clock') + '\n' +
                                t('web.common.cancel') + ': ' + t('web.timezone.keep_moment'));
                            if (keepClock) {
                                await fetch('/tasks/retime', {
                                    method: 'POST',
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify({timezone: q.new})
                                });
                            }
                        }
                        // Reload the page to show updated configuration
                        setTimeout(() => {
                            window.location.reload();
                        }, 1000);
                    } else {
                        // Check for permission errors
                        if (result.permission_errors && result.permission_errors.length > 0) {
                            let errorMessage = t('config.files_not_writable') + ':\n\n';
                            result.permission_errors.forEach(error => {
                                errorMessage += `• ${error}\n`;
                            });
                            errorMessage += '\n' + t('config.check_server_logs');
                            showAlert(errorMessage, 'danger');
                        } else {
                            showAlert(result.message || t('config.failed_save'), 'danger');
                        }
                    } 