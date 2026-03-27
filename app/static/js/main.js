                    const result = await response.json();
                    
                    if (result.success) {
                        // Clear unsaved changes flag
                        hasUnsavedChanges = false;
                        
                        showAlert(t('config.save_success'), 'success');
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