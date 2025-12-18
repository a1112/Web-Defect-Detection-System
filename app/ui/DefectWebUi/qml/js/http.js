.pragma library

function joinQuery(params) {
    if (!params) {
        return ""
    }
    const parts = []
    for (const key in params) {
        if (!Object.prototype.hasOwnProperty.call(params, key)) {
            continue
        }
        const value = params[key]
        if (value === null || value === undefined || value === "") {
            continue
        }
        parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(value))
    }
    return parts.length ? "?" + parts.join("&") : ""
}

function resolveUrl(baseUrl, path, params) {
    const query = joinQuery(params)
    if (!baseUrl) {
        return path + query
    }
    const trimmedBase = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl
    const normalizedPath = path.startsWith("/") ? path : "/" + path
    return trimmedBase + normalizedPath + query
}

function getJson(url, onSuccess, onError) {
    const xhr = new XMLHttpRequest()
    xhr.open("GET", url)
    xhr.setRequestHeader("Accept", "application/json")
    xhr.onreadystatechange = function () {
        if (xhr.readyState !== XMLHttpRequest.DONE) {
            return
        }
        if (xhr.status >= 200 && xhr.status < 300) {
            try {
                const parsed = JSON.parse(xhr.responseText)
                onSuccess(parsed)
            } catch (e) {
                onError("Invalid JSON response")
            }
            return
        }
        const message = xhr.responseText && xhr.responseText.length < 400
            ? xhr.responseText
            : ("HTTP " + xhr.status + " " + xhr.statusText)
        onError(message)
    }
    xhr.onerror = function () {
        onError("Network error")
    }
    xhr.send()
}
