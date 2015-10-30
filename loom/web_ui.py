import os
import multiprocessing
import threading
import time
import pdb
import flask
import sys
import logging
import uuid
import numpy
import bokeh

from StringIO import StringIO
from io import BytesIO
from Queue import Empty as QueueEmpty
#sys.stdout = sys.stderr

from api import (
    get_loom_dir,
    get_logging_handler,
    set_logging,
    load_config,
    load_spectral_network,
    generate_spectral_network,
)
from config import LoomConfig
from bokeh_plot import get_spectral_network_bokeh_plot

# Flask configuration
DEBUG = True
SECRET_KEY = 'web_loom_key'
PARENT_LOGGER_NAME = 'loom'
WEB_APP_NAME = 'web_loom'
LOGGING_FILE_PATH = os.path.join(
    get_loom_dir(),
    'logs/web_loom.log',
)
#MAX_NUM_PROCESSES = 4
DB_CLEANUP_CYCLE_SECS = 60
LOOM_PROCESS_JOIN_TIMEOUT_SECS = 3

# TODO: kill an orphaned process gracefully.
class LoomDB(object):
    """
    The internal DB to manage loom processes.
    """
    def __init__(self):
        self.logging_queues = {}
        self.result_queues = {}
        self.loom_processes = {}
        self.is_alive = {}

        self.db_manager = threading.Thread(
            target=self.db_manager,
        )
        self.db_manager.daemon = True
        self.db_manager.start()

    def db_manager(self):
        """
        A child process that will manage the DB
        and clean up data of previous clients.
        """
        logger_name = get_logger_name()
        logger = logging.getLogger(logger_name)

        while True:
            try:
                for process_uuid, alive in self.is_alive.iteritems():
                    if alive is True:
                        # Reset the heartbeat counter so that
                        # it can be cleaned up later.
                        self.is_alive[process_uuid] = False
                    else:
                        self.finish_loom_process(process_uuid)

                        try:
                            # Flush the result queue.
                            result_queue = self.result_queues[process_uuid]
                            while result_queue.empty() is False:
                                result_queue.get_nowait()
                            # Remove the result queue
                            del self.result_queues[process_uuid]
                        except KeyError:
                            logger.warning(
                                "Removing result queue {} failed: "
                                "no such a queue exists."
                                .format(process_uuid)
                            ) 
                            pass

                time.sleep(DB_CLEANUP_CYCLE_SECS)
            except (KeyboardInterrupt, SystemExit):
                break

    def start_loom_process(
        self, process_uuid, logging_level, loom_config, phase=None,
    ):
        logging_queue = multiprocessing.Queue()
        self.logging_queues[process_uuid] = logging_queue
        logger_name = get_logger_name(process_uuid)
        set_logging(
            logger_name=logger_name,
            logging_level=logging_level,
            logging_queue=logging_queue,
        )

        result_queue = multiprocessing.Queue()
        self.result_queues[process_uuid] = result_queue

        loom_process = multiprocessing.Process(
            target = generate_spectral_network,
            args=(
                loom_config,
            ),
            kwargs=dict(
                phase=phase,
                result_queue=result_queue,
                logging_queue=logging_queue,
                logger_name=logger_name,
            ),
        )
        self.loom_processes[process_uuid] = loom_process
        self.is_alive[process_uuid] = True
        loom_process.start()

        return None

    def get_log_message(
        self, process_uuid, logging_stream, logging_stream_handler
    ):
        record = self.logging_queues[process_uuid].get(True, 3)
        if record is not None:
            logging_stream_handler.handle(record)
            logs = logging_stream.getvalue()
            logging_stream.truncate(0)
            return logs
        else:
            raise QueueEmpty

    def yield_log_message(self, process_uuid, logging_level,):
        logging_stream = StringIO()
        logging_stream_handler = get_logging_handler(
            logging_level,
            logging.StreamHandler,
            logging_stream,
        )

        while self.result_queues[process_uuid].empty() is True:
            try:
                logs = self.get_log_message(process_uuid, logging_stream,
                                            logging_stream_handler,)
                yield 'data: {}\n\n'.format(logs)
            except QueueEmpty:
                pass 
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                import traceback
                print >> sys.stderr, 'logging_listener_process:'
                traceback.print_exc(file=sys.stderr)

        # Get the remaining logs, if any.
        while True:
            try:
                logs = self.get_log_message(process_uuid, logging_stream,
                                            logging_stream_handler,)
                yield 'data: {}\n\n'.format(logs)
            except QueueEmpty:
                break 
            except (KeyboardInterrupt, SystemExit):
                raise
        yield 'event: finish\ndata: \n\n'

    def get_result(self, process_uuid):
        logger_name = get_logger_name(process_uuid)
        logger = logging.getLogger(logger_name)

        rv = None

        result_queue = self.result_queues[process_uuid]
        loom_process = self.loom_processes[process_uuid]

        if result_queue.empty() is True:
            if loom_process.is_alive():
                logger.warning('Process {} still alive.'.format(name))
                return rv 
            else:
                logger.warning(
                    'Generating spectral networks failed: '
                    'pid = {}, exitcode = {}.'
                    .format(loom_process.pid,
                            loom_process.exitcode,)
                )
                return rv 
        else:
            # Result queue has the data returned from the loom_process.
            rv = result_queue.get()
            logger.info('Finished generating spectral network data.')
            self.finish_loom_process(process_uuid)
            return rv 

    def finish_loom_process(self, process_uuid):
        logger_name = get_logger_name(process_uuid)
        logger = logging.getLogger(logger_name)
        web_loom_logger = logging.getLogger(get_logger_name())

        try:
            # Terminate the loom_process.
            loom_process = self.loom_processes[process_uuid]

            loom_process.join(LOOM_PROCESS_JOIN_TIMEOUT_SECS)
            if loom_process.is_alive():
                loom_process.terminate()

            del self.loom_processes[process_uuid]
        except KeyError:
            web_loom_logger.warning(
                "Terminating loom_process {} failed: no such a process exists."
                .format(logger_name)
            ) 
            pass

        try:
            # Remove the logging queue handler.
            logger.handlers = []
            # Remove the logger.
            del logging.Logger.manager.loggerDict[logger_name]
        except KeyError:
            web_loom_logger.warning(
                "Removing logger {} failed: no such a logger exists."
                .format(logger_name)
            ) 
            pass

        try:
            # Flush the logging queue.
            logging_queue = self.logging_queues[process_uuid]
            while logging_queue.empty() is True:
                logging_queue.get_nowait()
            # Remove the logging queue.
            del self.logging_queues[process_uuid]
        except KeyError:
            web_loom_logger.warning(
                "Removing logging queue {} failed: no such a queue exists."
                .format(process_uuid)
            ) 
            pass


class WebLoomApplication(flask.Flask):
    """
    A wrapper of Flask application containing an instance of LoomDB.
    """
    def __init__(self, config_file, logging_level):
        super(WebLoomApplication, self).__init__(WEB_APP_NAME)
        set_logging(
            logger_name=WEB_APP_NAME,
            logging_level=logging_level,
            logging_file_name=LOGGING_FILE_PATH,
        )
        self.loom_db = LoomDB()

###
# View functions
###
def index():
    return flask.render_template('index.html')

def config():
    # Array of ('entry label', 'config option') pairs. 
    # Entries that will be placed in the same row
    # are in the same row of this array.
    config_items = [
        [('Description', 'description')],
        #[('Root System', 'root_system'),
        # ('Representation', 'representation')],
        [('Casimir differentials', 'casimir_differentials')],
        [('Parameters of differentials','differential_parameters')],
        [('Punctures', 'punctures')],
        [('Mobius transformation', 'mt_params')], 
        [('Ramification point finding method', 
          'ramification_point_finding_method'),],
        [('Plot range', 'plot_range')],
        [('Number of steps', 'num_of_steps')],
        [('Number of iterations', 'num_of_iterations')],
        [('Size of a small step', 'size_of_small_step')],
        [('Size of a large step', 'size_of_large_step')],
        [('Size of a branch point cutoff', 'size_of_neighborhood')],
        [('Size of a puncture cutoff', 'size_of_puncture_cutoff')],
        #[('Size of an intersection bin', 'size_of_bin')],
        #[('', 'size_of_ramification_pt_cutoff')],
        [('Accuracy', 'accuracy')],
        #[('Number of processes', 'n_processes')],
        [('Mass limit', 'mass_limit')],
        [('Range of phases', 'phase_range')],
    ]
    loom_config = None
    event_source_url = None
    text_area_content = '' 
    #plot_url = None
    n_processes = None 
    process_uuid = None

    if flask.request.method == 'GET':
        # Load the default configuration.
        loom_config = get_loom_config()
        try:
            n_processes = flask.request.args['n']
        except KeyError:
            pass

    elif flask.request.method == 'POST':
        try:
            uploaded_config_file = flask.request.files['config_file']
        except KeyError:
            uploaded_config_file = None

        if uploaded_config_file is not None:
            loom_config = LoomConfig(logger_name=logger_name)
            loom_config.read(uploaded_config_file)
            
        else:
            phase = eval(flask.request.form['phase'])
            process_uuid = str(uuid.uuid4())
            logger_name = get_logger_name(process_uuid)
            loom_config = get_loom_config(flask.request.form, logger_name) 
            #app = flask.current_app._get_current_object()
            app = flask.current_app
            app.loom_db.start_loom_process(
                process_uuid, logging.INFO, loom_config, phase,
            )
            event_source_url = flask.url_for(
                'logging_stream', process_uuid=process_uuid,
            )
            text_area_content = (
                "Start loom, uuid = {}".format(process_uuid)
            )
            #plot_url = flask.url_for('plot')

    return flask.render_template(
        'config.html',
        config_items=config_items,
        loom_config=loom_config,
        n_processes=n_processes,
        process_uuid=process_uuid,
        event_source_url=event_source_url,
        text_area_content=text_area_content,
        #plot_url=plot_url,
    )

def logging_stream(process_uuid):
    if flask.request.headers.get('accept') == 'text/event-stream':
        app = flask.current_app
        return flask.Response(
            app.loom_db.yield_log_message(process_uuid, logging.INFO),
            mimetype='text/event-stream',
        )

def save_config():
    loom_config = get_loom_config(flask.request.form)
    loom_config_fp = BytesIO()
    loom_config.parser.write(loom_config_fp)
    loom_config_fp.seek(0)
    rv = flask.send_file(loom_config_fp, mimetype='text/plain',
                         as_attachment=True,
                         attachment_filename='config.ini',
                         add_etags=True,)
    return rv
        

def plot():
    loom_db = flask.current_app.loom_db

    if flask.request.method == 'POST':
        process_uuid = flask.request.form['process_uuid']
        # Finish loom_process
        rv = loom_db.get_result(process_uuid)

    elif flask.request.method == 'GET':
        process_uuid = data_dir = flask.request.args['data']
        full_data_dir = os.path.join(
            get_loom_dir(), 'data', data_dir
        )
        rv = load_spectral_network(
            full_data_dir, logger_name=get_logger_name()
        )
        loom_db.result_queues[data_dir] = multiprocessing.Queue()

    loom_config, spectral_network_data = rv

    # Make a Bokeh plot
    bokeh_layout = get_spectral_network_bokeh_plot(spectral_network_data)
    script, div = bokeh.embed.components(bokeh_layout)
    legend = get_plot_legend(spectral_network_data.sw_data)

    # Put data back into the queue for future use.
    loom_db.result_queues[process_uuid].put(rv)

    return flask.render_template(
        'plot.html',
        process_uuid=process_uuid,
        plot_script=script,
        plot_div=div,
        plot_legend=legend,
        download_data_url=flask.url_for('download_data',
                                        process_uuid=process_uuid,),
        download_plot_url=flask.url_for('download_plot',
                                        process_uuid=process_uuid,),
    )

def download_data(process_uuid):
    pass

def download_plot(process_uuid):
    pass

def keep_alive(process_uuid):
    """
    Receive heartbeats from clients.
    """
    app = flask.current_app
    app.loom_db.is_alive[process_uuid] = True
    return ('', 204)
        

def admin():
    # TODO: password-protect this page.
    app = flask.current_app
    loom_db = app.loom_db
    pdb.set_trace()
    return ('', 204)

###
# Entry point
###

def get_application(config_file, logging_level):
    application = WebLoomApplication(config_file, logging_level)
    application.config.from_object(__name__)
    application.add_url_rule(
        '/', 'index', index, methods=['GET'],
    )
    application.add_url_rule(
        '/config', 'config', config, methods=['GET', 'POST'],
    )
    application.add_url_rule(
        '/save_config', 'save_config', save_config, methods=['POST'],
    )
    application.add_url_rule(
        '/plot', 'plot', plot,
        methods=['GET', 'POST'],
    )
    application.add_url_rule(
        '/download_data/<process_uuid>', 'download_data', download_data,
        methods=['POST'],
    )
    application.add_url_rule(
        '/download_plot/<process_uuid>', 'download_plot', download_plot,
        methods=['POST'],
    )
    application.add_url_rule(
        '/logging_stream/<process_uuid>', 'logging_stream', logging_stream,
        methods=['GET'],
    )
    application.add_url_rule(
        '/keep_alive/<process_uuid>', 'keep_alive', keep_alive,
        methods=['GET'],
    )
    application.add_url_rule(
        '/admin', 'admin', admin,
        methods=['GET'],
    )
    return application

###
# Misc. web UIs
###

def get_logger_name(uuid=None):
    logger_name = WEB_APP_NAME
    if uuid is not None:
        logger_name += '.' + uuid
    return logger_name

def get_loom_config(request_dict=None, logger_name=get_logger_name()):
    logger = logging.getLogger(logger_name)

    default_config_file = os.path.join(
        get_loom_dir(),
        'config/default.ini',
    )
    loom_config = load_config(default_config_file, logger_name=logger_name)

    if request_dict is not None:
        # Update config with form data.
        root_system = request_dict['type'] + request_dict['rank']
        for section in loom_config.parser.sections():
            for option in loom_config.parser.options(section):
                try:
                    if option == 'root_system':
                        value = root_system
                    else:
                        value = request_dict[option]
                    if (section == 'numerical parameters'):
                        loom_config[option] = eval(value)
                    else:
                        loom_config[option] = value
                    loom_config.parser.set(section, option, value)
                except KeyError:
                    logger.warning(
                        'No entry for option = {}, skip it.'
                        .format(option)
                    )
                    pass

    return loom_config

def get_plot_legend(sw_data):
    legend = ''
    g_data = sw_data.g_data
    roots = g_data.roots
    weights = g_data.weights
    weight_pairs=[
        [str('(mu_'+str(p[0])+', mu_'+str(p[1])+')') 
         for p in g_data.ordered_weight_pairs(rt)]
        for rt in roots
    ]

    legend += ('\t--- The Root System ---\n')
    for i in range(len(roots)):
        legend += (
            'alpha_' + str(i) + ' : {}\n'.format(list(roots[i])) +
            'ordered weight pairs : {}\n'.format(weight_pairs[i])
        )

    legend += ('\t--- The Weight System ---\n')
    for i in range(len(weights)):
        legend += (
            'nu_' + str(i) + ' : {}\n'.format(list(weights[i]))
        )

    legend += ('\t--- The Branch Points ---\n')
    for bp in sw_data.branch_points:
        root_labels = []
        for pr in bp.positive_roots:
            for i, r in enumerate(roots):
                if numpy.array_equal(pr, r):
                    root_labels.append('alpha_{}'.format(i)) 
        legend += (
            '\n{}\n'.format(bp.label) +
            'position : {}\n'.format(bp.z) +
            'root type : {}\n'.format(root_labels) +
            'monodromy matrix : \n{}\n'.format(bp.monodromy)
        )

    legend += ('\t--- The Irregular Singularities ---\n')
    for irs in sw_data.irregular_singularities:
        legend += (
            '\n{}\n'.format(irs.label) +
            'position : {}\n'.format(irs.z) + 
            'monodomry matrix : \n{}\n'.format(irs.monodromy)
        )

    return legend


