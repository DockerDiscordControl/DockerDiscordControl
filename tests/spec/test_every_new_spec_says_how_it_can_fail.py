# -*- coding: utf-8 -*-
"""A new specification says how it could fail.

The rule this project's tests are written by: a test that has never been red
proves nothing, so every spec file says in its docstring what was changed to
make it fail - the finding it was written against, or the sabotage that turned
it red afterwards. It is the one line a reader can check.

123 files predate the convention (they were written before it was stated) and
are listed below. The list may only ever get shorter: a file that gains its
note leaves it, and a NEW file that does not carry one fails here.

COUNTER-CHECK (2026-09-22): removing a name from the list turns this red for
that file; adding a spec file without the words turns it red too (checked with
a throwaway file).
"""

import glob
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Measured 2026-09-22. May only shrink - never add a name here.
WITHOUT_A_NOTE = {
    "test_a_background_loop_survives_one_bad_cycle.py",
    "test_a_bad_keyword_is_reported_not_raised.py",
    "test_a_button_press_never_ends_on_processing.py",
    "test_a_button_that_fails_says_so.py",
    "test_a_damaged_mech_does_not_silence_the_appeal.py",
    "test_a_damaged_mech_does_not_stop_the_bot.py",
    "test_a_failed_fetch_is_not_silently_dropped.py",
    "test_a_password_protects_on_every_path.py",
    "test_a_password_that_did_not_change_says_so.py",
    "test_a_refresh_button_survives_a_lost_docker.py",
    "test_a_refused_purge_still_deletes_what_it_may.py",
    "test_a_reset_is_not_announced_as_a_donation.py",
    "test_a_retest_that_never_starts_leaves_no_spinner.py",
    "test_a_schedule_does_not_act_on_an_unreadable_config.py",
    "test_a_setup_that_cannot_save_says_so.py",
    "test_a_slash_command_error_reaches_the_user.py",
    "test_a_switch_that_says_off_is_not_read_as_on.py",
    "test_a_task_is_not_deleted_because_checking_failed.py",
    "test_a_task_that_failed_says_so_on_the_task.py",
    "test_a_temp_file_that_cannot_be_created_is_handled.py",
    "test_action_log_download_serves_the_written_file.py",
    "test_addadmin_has_the_same_brake.py",
    "test_an_address_the_panel_shows_can_exist.py",
    "test_an_admin_may_be_scoped_to_containers.py",
    "test_an_assigned_admin_controls_only_his_containers.py",
    "test_an_empty_translation_falls_back.py",
    "test_an_ordinary_render_is_not_critical.py",
    "test_an_unchanged_member_count_writes_nothing.py",
    "test_an_undecryptable_token_does_not_kill_the_bot.py",
    "test_an_unreachable_docker_is_reported_not_raised.py",
    "test_an_unreadable_task_file_is_not_an_empty_one.py",
    "test_bandit_scan_excludes_its_directories.py",
    "test_bot_strings_exist_in_the_catalog.py",
    "test_buttons_brake_by_button_sliders.py",
    "test_channel_form_reads_every_row.py",
    "test_ci_python_is_the_shipped_python.py",
    "test_codebase_is_english.py",
    "test_commands_brake_through_the_service.py",
    "test_config_dir_active_containers.py",
    "test_config_dir_admins.py",
    "test_config_dir_auto_actions.py",
    "test_config_dir_container_info_save.py",
    "test_config_dir_containers_and_channels.py",
    "test_config_dir_donation_notification.py",
    "test_config_dir_mech.py",
    "test_config_dir_single_owners.py",
    "test_config_dir_single_source.py",
    "test_config_dir_spam_protection.py",
    "test_config_dir_token.py",
    "test_connectivity_embed_speaks_the_server_language.py",
    "test_coverage_by_file_is_complete.py",
    "test_default_values_do_not_contradict.py",
    "test_disabled_donations_really_remove_the_commands.py",
    "test_durable_files_are_written_atomically.py",
    "test_enable_info_placeholder_says_enable.py",
    "test_encrypting_the_token_never_answers_a_blank_page.py",
    "test_every_cog_module_is_reachable.py",
    "test_every_day_of_the_month_can_be_picked.py",
    "test_every_translation_can_be_formatted.py",
    "test_every_ui_class_is_ever_built.py",
    "test_every_workflow_limits_its_token.py",
    "test_four_buttons_brake_through_the_service.py",
    "test_heartbeat_decision_survives_a_null_url.py",
    "test_info_buttons_brake_through_the_service.py",
    "test_live_log_view_brakes_through_the_service.py",
    "test_loading_status_fits_narrow_screens.py",
    "test_log_button_brakes_through_the_service.py",
    "test_mech_buttons_ask_their_own_slider.py",
    "test_mech_buttons_brake_through_the_service.py",
    "test_mech_decay_shipped.py",
    "test_mech_details_has_a_slider.py",
    "test_mech_history_button_always_acknowledges.py",
    "test_mech_speed_texts_shipped.py",
    "test_mech_stories_shipped.py",
    "test_no_button_is_shown_that_will_refuse.py",
    "test_no_cooldown_hook_pretends_to_guard.py",
    "test_no_except_clause_needs_a_missing_module.py",
    "test_no_guard_is_always_false.py",
    "test_no_method_is_defined_twice.py",
    "test_no_scheduling_helper_is_unreachable.py",
    "test_not_awaitable_error_helper.py",
    "test_per_minute_limits_really_brake.py",
    "test_processing_message_fits_narrow_screens.py",
    "test_protected_password_has_a_limit.py",
    "test_r2_spec_coverage.py",
    "test_requested_cooldown_keys_exist.py",
    "test_rule_cooldown_survives_one_failed_container.py",
    "test_saved_config_is_completed_from_defaults.py",
    "test_serverstatus_refuses_privately.py",
    "test_setup_alerts_show_text_not_markup.py",
    "test_status_shows_the_fresh_state_after_a_pending_action.py",
    "test_task_delete_button_refuses_translated.py",
    "test_the_action_log_rate_limit_is_the_one_that_runs.py",
    "test_the_admin_dropdown_checks_the_right.py",
    "test_the_bulk_buttons_answer_to_the_admin_list.py",
    "test_the_busiest_entry_is_not_the_one_evicted.py",
    "test_the_container_list_call_fits_docker.py",
    "test_the_donation_path_reads_fields_that_exist.py",
    "test_the_dropdown_offers_only_what_he_may_use.py",
    "test_the_duplicate_filter_measures_coverage.py",
    "test_the_goal_log_line_adds_up.py",
    "test_the_initial_status_send_exists_once.py",
    "test_the_log_service_has_no_unreachable_helper.py",
    "test_the_panel_can_assign_containers.py",
    "test_the_task_file_keeps_its_permissions.py",
    "test_toggle_button_has_a_cooldown_again.py",
    "test_toggle_button_slider_in_panel.py",
    "test_toggle_reports_a_config_failure.py",
    "test_translating_a_string_does_not_reload_the_config.py",
    "test_unbraked_mech_buttons_brake.py",
    "test_z1_corrupt_snapshot_keeps_the_readable_ledger.py",
    "test_z1_donation_effect_survives_a_failed_snapshot_write.py",
    "test_z1_partial_reset_is_reported_and_backed_up.py",
    "test_z3_booked_donation_is_reported_as_booked.py",
    "test_z5_admins_act_in_status_channels.py",
    "test_z5_revoked_permission_takes_effect_at_once.py",
    "test_z8_donation_helpers_log_their_errors.py",
    "test_z8_failed_donation_clears_the_processing_message.py",
    "test_z8_one_failing_listener_breaks_nothing_else.py",
    "test_z8_query_support_write_failure_is_visible.py",
    "test_z8_web_donation_announcement_is_not_lost_silently.py",
    "test_z9_protected_info_never_lands_in_the_log.py",
}


def _spec_files():
    for path in sorted(glob.glob(str(ROOT / "tests" / "spec" / "test_*.py"))):
        yield os.path.basename(path), Path(path).read_text(encoding="utf-8")


def test_every_new_spec_says_how_it_can_fail():
    silent = [name for name, text in _spec_files()
              if "counter-check" not in text.lower() and name not in WITHOUT_A_NOTE]
    assert not silent, ("these specs do not say how they could fail:\n" + "\n".join(silent))


def test_the_list_only_shrinks():
    names = {name for name, _ in _spec_files()}
    gone = WITHOUT_A_NOTE - names
    assert not gone, f"listed files that no longer exist: {sorted(gone)}"
    now_noted = [name for name, text in _spec_files()
                 if name in WITHOUT_A_NOTE and "counter-check" in text.lower()]
    assert not now_noted, ("these carry a note now and must leave the list:\n"
                           + "\n".join(now_noted))
