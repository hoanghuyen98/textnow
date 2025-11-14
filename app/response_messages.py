# app/constants/response_messages.py

PHONE_MESSAGES = {
    "missing_email": "Email is required to create a PhoneAccount.",
    "email_not_owned": "This email has not been purchased or does not belong to the employee.",
    "email_used": "This email has already been used for another account.",
    "validation_failed": "Validation failed.",
    "phone_created": "Phone created successfully (status: {status}).",
    "system_error": "System error while creating PhoneAccount.",
}


INBOX_MESSAGES = {
    "missing_phone": "Missing 'phone' parameter in query string.",
    "invalid_phone": "The provided phone number is invalid or not in 'live' status.",
    "missing_batch": "No batch script found for this phone number.",
    "curl_failed": "Failed to fetch message data. Status has been changed to 'die_use'.",
    "parse_failed": "Unable to parse message data from server.",
    "success": "Inbox loaded successfully.",
    "processing_error": "Error occurred while processing inbox data.",
}

SEND_MESSAGE_MESSAGES = {
    "missing_fields": "Missing required fields: phone / to / text.",
    "invalid_phone": "The provided phone number is invalid or not in 'live' status.",
    "missing_curl": "No message cURL configuration found for this phone number.",
    "send_failed": "Failed to send message.",
    "success": "Message sent successfully.",
}


SEND_MEDIA_MESSAGES = {
    "missing_fields": "Missing required fields: phone / to / file.",
    "invalid_phone": "The provided phone number is invalid or not in 'live' status.",
    "missing_curl": "No media cURL configuration found for this phone number.",
    "upload_error": "Error occurred while uploading image.",
    "invalid_upload_url": "Upload response does not contain a valid image URL.",
    "send_failed": "Failed to send media message.",
    "unknown_error": "Failed to send image message.",
    "success": "Media message sent successfully.",
}
