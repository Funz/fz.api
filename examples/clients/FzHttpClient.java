// Example fz-http client using only the JDK (java.net.http, Java 11+).
//
// Runs the full flow against a running server:
//   1. health check
//   2. parse an input template            (POST /parse)
//   3. launch a parametric run            (POST /runs)
//   4. poll the job until it completes    (GET  /runs/{id})
//
// No external dependencies: request bodies are built with a tiny JSON-string
// escaper, and the few fields we need are extracted from responses with regex.
// For real projects, prefer a JSON library (Jackson, Gson).
//
// Run (Java 17):
//   java FzHttpClient.java [BASE_URL]      // default http://localhost:8000

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class FzHttpClient {

    static String base = "http://localhost:8000";
    // Force HTTP/1.1: the default HTTP/2 upgrade is mishandled by the
    // uvicorn/h11 (HTTP/1.1-only) server and would drop the request body.
    static final HttpClient http =
            HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();

    // fz input template and calculator script (normal Java escapes).
    static final String INPUT_TXT =
            "n_mol=$n_mol\nT_kelvin=@{$T_celsius + 273.15}\nV_m3=$V_L\n";
    static final String CALC_SH =
            "#!/bin/bash\nsource \"$1\"\n"
          + "awk \"BEGIN{printf \\\"pressure = %.4f\\\", "
          + "$n_mol*8.314*$T_kelvin/$V_m3}\" > output.txt\n";
    static final String OUTPUT_CMD =
            "grep 'pressure = ' output.txt | awk '{print $3}'";

    public static void main(String[] args) throws Exception {
        if (args.length > 0) base = args[0];

        System.out.println("== health ==");
        System.out.println(get("/health"));

        System.out.println("\n== parse ==");
        String parseBody = "{"
              + "\"input_files\":{\"input.txt\":" + js(INPUT_TXT) + "},"
              + "\"model\":{\"varprefix\":\"$\",\"delim\":\"{}\"}"
              + "}";
        System.out.println(post("/parse", parseBody));

        System.out.println("\n== submit run ==");
        String runBody = "{"
              + "\"input_files\":{"
              +     "\"input.txt\":" + js(INPUT_TXT) + ","
              +     "\"calc.sh\":" + js(CALC_SH)
              + "},"
              + "\"input_path\":\"input.txt\","
              + "\"model\":{\"varprefix\":\"$\",\"delim\":\"{}\","
              +     "\"output\":{\"pressure\":" + js(OUTPUT_CMD) + "}},"
              + "\"input_variables\":{\"n_mol\":[1,2],\"T_celsius\":25,\"V_L\":10},"
              + "\"calculators\":[\"sh://bash calc.sh\"]"
              + "}";
        String ref = post("/runs", runBody);
        String jobId = extract(ref, "\"job_id\"\\s*:\\s*\"([^\"]+)\"");
        System.out.println("job_id = " + jobId);

        System.out.println("\n== poll ==");
        String status;
        String body;
        while (true) {
            body = get("/runs/" + jobId);
            status = extract(body, "\"status\"\\s*:\\s*\"([^\"]+)\"");
            System.out.println("status: " + status);
            if (status.equals("completed") || status.equals("failed")) break;
            Thread.sleep(1000);
        }
        System.out.println("\n== result ==");
        System.out.println(body);
    }

    static String get(String path) throws Exception {
        return send(HttpRequest.newBuilder(URI.create(base + path)).GET().build());
    }

    static String post(String path, String jsonBody) throws Exception {
        HttpRequest req = HttpRequest.newBuilder(URI.create(base + path))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                .build();
        return send(req);
    }

    static String send(HttpRequest req) throws Exception {
        HttpResponse<String> resp =
                http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() >= 400) {
            throw new RuntimeException(
                    "HTTP " + resp.statusCode() + ": " + resp.body());
        }
        return resp.body();
    }

    // Minimal JSON string escaper: wraps s in quotes and escapes it.
    static String js(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"':  b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n");  break;
                case '\r': b.append("\\r");  break;
                case '\t': b.append("\\t");  break;
                default:   b.append(c);
            }
        }
        return b.append("\"").toString();
    }

    static String extract(String json, String regex) {
        Matcher m = Pattern.compile(regex).matcher(json);
        if (!m.find()) throw new RuntimeException("field not found in: " + json);
        return m.group(1);
    }
}
