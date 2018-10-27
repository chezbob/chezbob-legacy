var coldbrew = {};

coldbrew.GRAPH_LABEL = 'Cold Brew';

coldbrew.CHART_OPTIONS = {
    width: 650,
    height: 650,
    greenFrom: 40,
    greenTo: COLDBREW_MAXIMUM,
    redFrom: 0,
    redTo: 10,
    yellowFrom: 10,
    yellowTo: 40,
    majorTicks: null,  // Defined in init();
    minorTicks: 10,
    max: COLDBREW_MAXIMUM,
};

coldbrew.NODE_NAME = 'coldbrew_gauge'; // for the websocket heartbeat

coldbrew._coffee_name = null;
coldbrew._coffee_desc = null;

coldbrew._out_of_order_overlay = null;

coldbrew.decrement_gauge = function() {
    console.log("Decrementing gauge");
    var new_value = Math.max(0, coldbrew.data.getValue(0, 1) - 1);
    coldbrew.data.setValue(0, 1, new_value);
    coldbrew.chart.draw(coldbrew.data, coldbrew.CHART_OPTIONS);
};

coldbrew.reset_gauge = function() {
    console.log("Reseting gauge");
    coldbrew.data.setValue(0, 1, COLDBREW_MAXIMUM);
    coldbrew.chart.draw(coldbrew.data, coldbrew.CHART_OPTIONS);
};

coldbrew.init_gauge = function() {
    coldbrew.data = google.visualization.arrayToDataTable([
        ['Label', 'Value'],
        [coldbrew.GRAPH_LABEL, 0],
    ]);

    coldbrew.chart = new google.visualization.Gauge(
        document.getElementById('chart_div'));

    coldbrew.chart.draw(coldbrew.data, coldbrew.CHART_OPTIONS);

    coldbrew.init_websockets();
};

coldbrew.get_ws_url = function() {
    // If we're serving from a local file, assume the ws host is localhost.
    if (document.location.origin == "file://") {
        return "ws://127.0.0.1:8090/ws";
    } else {
        return (document.location.protocol === "http:" ? "ws:" : "wss:") +
                "//" + document.location.host + "/ws";
    }
};

coldbrew.populate_gauge = function(session) {
    console.log("Fetching current gauge status");

    session.call('chezbob.coldbrew.get_keg_status', []).then(
        function(result) {
            console.log("Fetched:", result);

            // Update the gauge
            coldbrew.data.setValue(
                0, 1,
                Math.max(0, Math.floor((COLDBREW_MAXIMUM - result.n_sold))));
            coldbrew.chart.draw(coldbrew.data, coldbrew.CHART_OPTIONS);

            // Update the description
            coldbrew.set_coffee_details(result.name, result.description);

            // Is it out of order?
            coldbrew.out_of_order_toggle(result.out_of_order);
        },
        function (err) {
            console.log("Fetch error:", err);
        }
    );
};

coldbrew.set_coffee_details = function(name, description) {
    coldbrew._coffee_name.html(name);
    coldbrew._coffee_desc.html(description);
};

coldbrew.out_of_order_toggle = function(display) {
    if (display)
        coldbrew._out_of_order_overlay.removeClass("hidden");
    else
        coldbrew._out_of_order_overlay.addClass("hidden");
};

coldbrew.interpret_coldbrew_activity = function(args) {
    var activity = args[0];

    if (activity.type == "purchase") {
        coldbrew.decrement_gauge();
    }
    else if (activity.type == "restock") {
        coldbrew.reset_gauge();
        coldbrew.set_coffee_details(activity.name, activity.description);
    }
    else if (activity.type == "out_of_order") {
        coldbrew.out_of_order_toggle(true);
    }
    else if (activity.type == "in_to_order") {
        coldbrew.out_of_order_toggle(false);
    }
    else {
        console.log("Unrecognized activity:", activity);
    }
};

coldbrew.init_websockets = function() {
    var heartbeat_timer;

    var connection = new autobahn.Connection({
       url: coldbrew.get_ws_url(), realm: "chezbob"
    });

    connection.onopen = function (session, details) {
        console.log("Connected");

        coldbrew.populate_gauge(session);

        session.subscribe('chezbob.coldbrew.activity',
                          coldbrew.interpret_coldbrew_activity)
            .then(
                function() { console.log('Subscribed to activity'); },
                function(err) {
                    console.log('Failed subscription for activity', err);
                }
            );

        heartbeat_timer = setInterval(function () {
           session.publish('chezbob.heartbeat', [coldbrew.NODE_NAME]);
        }, 1000);
    };

    connection.onclose = function (reason, details) {
        console.log("Connection lost: " + reason);

        // Clear the heartbeat, if relevant.
        if (heartbeat_timer) {
           clearInterval(heartbeat_timer);
           heartbeat_timer = null;
        }

        // Fall back on polling if we couldn't get them.
        if (reason == "unreachable") {
            console.log("WS connection failed.");
        }
        else if (reason == "lost")
            console.log("WS connection lost-- auto reconnecting.");
    };

    connection.open();
};

coldbrew.init = function() {
    // Generate the chart ticks / labels
    var n_ticks = COLDBREW_MAXIMUM / 5 + 1;
    coldbrew.CHART_OPTIONS.majorTicks = ["E"]; // empty at the bottom
    for (var i = 1; i < n_ticks - 1; i++) {
        coldbrew.CHART_OPTIONS.majorTicks.push(""); // nothing in the middle
    }
    coldbrew.CHART_OPTIONS.majorTicks.push("F"); // full at the top

    // Load the gauge
    google.charts.load('current', { 'packages': ['gauge'] });
    google.charts.setOnLoadCallback(coldbrew.init_gauge);

    // Grab elements for later populating
    coldbrew._coffee_name = $("#coffee_name");
    coldbrew._coffee_desc = $("#coffee_description");

    coldbrew._out_of_order_overlay = $("#out_of_order_overlay");
};
